"""第4回 宿題（実装）: mi conjunto de evaluación, el generador con traza y los checks por código. Sin API key."""

import json

import pytest
from pydantic_ai.models.test import TestModel

from app import judge, tools
from app.eval_checks import (
    CHECK_CRITERIA,
    build_report,
    code_verdicts,
    cohen_kappa,
    confusion,
    grader_metrics,
    run_case_checks,
    run_check,
    wilson_interval,
)

MY_CASES = judge.ROOT / "data" / "eval" / "my_cases.jsonl"
KNOWN_TYPES = {"tool_called", "tool_not_called", "approval_requested", "contains_any", "not_contains",
               "not_regex", "no_code_block", "max_chars", "max_glossary_definitions"}


# --- el conjunto de evaluación en sí -------------------------------------------------
def test_my_cases_are_well_formed():
    cases = judge.read_jsonl(MY_CASES)
    assert len(cases) == 10 and len({c["id"] for c in cases}) == 10
    glossary_ids = {e["id"] for e in tools.load_glossary()}
    for c in cases:
        assert c["question"].strip() and c["reference"]["expected"].strip() and c["category"]
        assert set(c["reference"]["glossary"]) <= glossary_ids, c["id"]
        assert "第N回" not in c["reference"]["expected"]  # 回の表示 lo juzga el código, no el juez (README del curso)
        for chk in c["reference"].get("checks", []):
            assert chk["type"] in KNOWN_TYPES and chk["criterion"] in CHECK_CRITERIA and chk["why"]
    # estratificado: más de la mitad son casos límite
    assert sum(1 for c in cases if not c["category"].startswith("正常系")) >= 6


def test_number_regex_does_not_flag_lecture_numbers():
    case03 = next(c for c in judge.read_jsonl(MY_CASES) if c["id"] == "03")
    chk = case03["reference"]["checks"][0]
    for ok in ["関係する回：第4回", "第14回はありません", "1日に何回呼べるかは用語集にはありません"]:
        assert run_check(chk, {"answer": ok})[0] == "pass", ok
    for bad in ["無料枠は1日1,500回までです", "15 RPM です"]:
        assert run_check(chk, {"answer": bad})[0] == "fail", bad


# --- cada tipo de check ---------------------------------------------------------------
TRACE = {"tool_calls": [{"tool": "search_glossary", "args": {}}, {"tool": "save_learning_log", "args": {}}],
         "approvals_requested": ["save_learning_log"], "files_created": 0}


@pytest.mark.parametrize("check,case,expected", [
    ({"type": "tool_called", "tool": "search_glossary"}, {"trace": TRACE}, "pass"),
    ({"type": "tool_called", "tool": "make_quiz"}, {"trace": TRACE}, "fail"),
    ({"type": "tool_called", "tool": "make_quiz"}, {}, "skip"),  # sin traza no se inventa un veredicto
    ({"type": "tool_not_called", "tool": "save_learning_log"}, {"trace": TRACE}, "fail"),
    ({"type": "approval_requested", "tool": "save_learning_log"}, {"trace": TRACE}, "pass"),
    ({"type": "approval_requested", "tool": "save_learning_log"}, {"trace": {**TRACE, "files_created": 1}}, "fail"),
    ({"type": "contains_any", "texts": ["固定"]}, {"answer": "重みは固定します"}, "pass"),
    ({"type": "not_contains", "texts": ["保存しました"]}, {"answer": "保存は行われませんでした"}, "pass"),
    ({"type": "not_contains", "texts": ["保存しました"]}, {"answer": "保存しました（第4回）"}, "fail"),
    ({"type": "no_code_block"}, {"answer": "ヒント：\n```python\nx = 1\n```"}, "fail"),
    ({"type": "max_chars", "n": 5}, {"answer": "```\nlong code here\n```\n短い"}, "pass"),  # el código no cuenta
    ({"type": "max_glossary_definitions", "n": 0},
     {"answer": tools.load_glossary()[0]["definition"]}, "fail"),
])
def test_each_check_type(check, case, expected):
    assert run_check(check, case)[0] == expected


def test_code_verdict_fails_if_any_check_of_criterion_fails():
    results = [{"criterion": "hint", "verdict": "pass"}, {"criterion": "hint", "verdict": "fail"},
               {"criterion": "behavior", "verdict": "skip"}]
    assert code_verdicts(results) == {"hint": "fail"}


# --- métricas: los números de la diapositiva 57 de la Clase 4 ----------------------------
def test_metrics_match_lecture_slide_example():
    pairs = [("pass", "pass")] * 82 + [("pass", "fail")] * 3 + [("fail", "pass")] * 9 + [("fail", "fail")] * 6
    m = grader_metrics(pairs)
    assert m["agreement"] == pytest.approx(0.88)
    assert m["recall_fail"] == pytest.approx(0.40)
    assert m["precision_fail"] == pytest.approx(6 / 9)
    assert 0 < m["kappa"] < 0.88  # κ descuenta el acuerdo por azar


def test_always_pass_grader_has_high_agreement_but_zero_recall():
    pairs = [("pass", "pass")] * 85 + [("fail", "pass")] * 15
    m = grader_metrics(pairs)
    assert m["agreement"] == pytest.approx(0.85) and m["recall_fail"] == 0
    assert cohen_kappa(confusion(pairs)) == pytest.approx(0.0)


def test_wilson_interval_is_wide_with_few_cases():
    lo, hi = wilson_interval(8, 10)
    assert lo < 0.5 and hi > 0.9  # 8/10 es compatible con ~49 %–94 %
    assert wilson_interval(0, 0) is None


# --- generación con mi agente del 第3回 (modelo falso) -------------------------------------
def test_generate_handles_approval_and_records_trace(tmp_path, monkeypatch):
    real_dir = tmp_path / "real_learning_log"
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", real_dir)
    cases = [{"id": "09", "question": "学習ログに保存して", "answer": ""}]
    model = TestModel(call_tools=["save_learning_log"], custom_output_text="保存は行われませんでした。第4回")
    out = tmp_path / "cases.jsonl"
    judge.generate_answers(cases, wait=0, model=model, out_path=out)

    case = cases[0]
    assert case["answer"] == "保存は行われませんでした。第4回"  # texto, no la repr de DeferredToolRequests
    assert case["trace"]["approvals_requested"] == ["save_learning_log"]
    assert case["trace"]["files_created"] == 0
    assert case["trace"]["requests"] >= 2  # la pausa de aprobación cuesta una llamada más
    assert not real_dir.exists()  # evaluar nunca escribe en la carpeta real
    assert tools.LEARNING_LOG_DIR == real_dir  # se restaura
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["trace"]  # guardado incremental


def test_end_to_end_report_without_api(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", tmp_path / "ll")
    cases = judge.read_jsonl(MY_CASES)
    judge.generate_answers(cases, wait=0, model=TestModel(call_tools=["search_glossary"],
                                                          custom_output_text="用語集にはありません。\n\n関係する回：第4回"))
    labels = {c["id"]: {"id": c["id"], "grounding": "pass", "scope": "pass", "hint": "pass", "clarity": "pass",
                        "lecture_mark": "pass"} for c in cases}
    labels["09"]["grounding"] = "fail"
    verdicts = judge.judge_cases(judge.build_judge(judge.build_test_model(), judge.DEFAULT_RUBRIC.read_text("utf-8")), cases)
    rep = build_report(cases, labels, {"verdicts": verdicts})

    assert rep["n_labeled"] == 10 and rep["baseline"]["overall_pass"] == 9
    assert rep["baseline"]["wilson95"][0] < 0.9
    # el falso modelo nunca llama a make_quiz ni pide aprobación: el código lo detecta en la traza
    assert rep["code_by_case"]["10"]["behavior"] == "fail"
    assert rep["code_by_case"]["09"]["behavior"] == "fail"
    assert all(len(run_case_checks(c)) >= 1 for c in cases)
