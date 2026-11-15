"""第2回 宿題（発展）のテスト。GPU も API キーも不要。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import glossary_ft as gft  # noqa: E402
import make_glossary_data  # noqa: E402

GLOSSARY = gft.load_glossary(ROOT / "data" / "glossary.json")


def test_v1_identico_al_script_del_curso():
    """El JSONL v1 debe ser exactamente lo que imprime scripts/make_sft_dataset.py."""
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_sft_dataset.py")],
                         capture_output=True, text=True, check=True).stdout
    expected = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gft.build_sft_records(GLOSSARY, "v1"))
    assert out == expected
    assert len(out.splitlines()) == 2 * len(GLOSSARY)


def test_formato_messages():
    for r in gft.build_sft_records(GLOSSARY, "v2"):
        assert [m["role"] for m in r["messages"]] == ["user", "assistant"]
        assert all(isinstance(m["content"], str) and m["content"] for m in r["messages"])


def test_eval_sin_fuga_y_terminos_ausentes_de_verdad():
    items = gft.build_eval_items(GLOSSARY)
    assert gft.check_no_leak(gft.build_sft_records(GLOSSARY, "v2"), items) == []
    assert gft.check_absent_terms(GLOSSARY) == []
    # 'seen' sí debe estar en el entrenamiento (fuga intencional y etiquetada)
    train_q = {r["messages"][0]["content"] for r in gft.build_sft_records(GLOSSARY, "v1")}
    assert all(i["question"] in train_q for i in items if i["category"] == "seen")
    assert len({i["question"] for i in items}) == len(items)


def test_la_definicion_de_referencia_pasa_su_propio_criterio():
    for it in gft.build_eval_items(GLOSSARY):
        if it["term_id"]:
            assert gft.score_output(it, it["reference"], GLOSSARY)["verdict"] == "correct", it["term_id"]


def test_umbral_de_contaminacion_por_encima_de_definiciones_distintas():
    assert gft.calibrate_contamination(GLOSSARY)["max"] < gft.CONTAMINATION_F1


@pytest.mark.parametrize("question, expected", [
    ("AIE2026の講座の宿題にある「3レベル」とは何ですか？", "homework-levels"),
    ("Low-Rank Adaptationについて教えてください。", "lora"),
    ("LLMとは？", "llm"),
    ("pipelineの使い方", None),          # "pi" no debe coincidir dentro de "pipeline"
    ("日本の首都はどこですか？", None),
])
def test_lookup(question, expected):
    hits = gft.lookup(question, GLOSSARY)
    assert (hits[0]["id"] if hits else None) == expected


def test_clasificacion():
    items = {i["category"]: i for i in gft.build_eval_items(GLOSSARY)}
    fic, gen = items["fictional"], items["general"]
    assert gft.score_output(fic, "用語集に記載がありません。", GLOSSARY)["verdict"] == "refused"
    assert gft.score_output(fic, "量子トークン圧縮はトークンを減らす技術です。", GLOSSARY)["verdict"] == "hallucinated"
    lora_def = next(e["definition"] for e in GLOSSARY if e["id"] == "lora")
    assert gft.score_output(gen, lora_def, GLOSSARY)["verdict"] == "contaminated"
    assert gft.score_output(gen, "東京です。", GLOSSARY)["verdict"] == "ok"


def test_rag_messages_incluye_definicion_o_aviso():
    msgs = gft.rag_messages("LoRAとは？", GLOSSARY)
    assert msgs[0]["role"] == "system" and "低ランク" in msgs[0]["content"]
    assert "該当する用語はありません" in gft.rag_messages("日本の首都は？", GLOSSARY)[0]["content"]


def test_cli_eval_y_baseline(tmp_path):
    ev, out = tmp_path / "eval.jsonl", tmp_path / "search.json"
    make_glossary_data.main(["eval", "--out", str(ev)])
    make_glossary_data.main(["search-baseline", "--eval", str(ev), "--out", str(out)])
    summary = json.loads(out.read_text(encoding="utf-8"))["summary"]
    assert summary["by_category"]["seen"]["correct"] == summary["by_category"]["seen"]["n"]
