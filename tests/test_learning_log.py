"""宿題（実装）: save_learning_log と承認フローのテスト（LLM・APIキーは使わない）。

TestModel は登録されたツールを呼ぶ偽モデル。承認が必要なツールは実行されずに
DeferredToolRequests で止まるので、「承認 → 保存」「拒否 → 保存しない」をAPIなしで確かめられる。
"""

import json
from datetime import datetime

import pytest
from pydantic_ai import ToolDenied
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel

from app import agent as agent_module
from app import tools


@pytest.fixture(autouse=True)
def tmp_log_dir(tmp_path, monkeypatch):
    """Cada test escribe en una carpeta temporal, nunca en learning_log/ del repo."""
    log_dir = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", log_dir)
    return log_dir


# --- herramienta: validación, ruta, idempotencia --------------------------------


def test_save_creates_markdown_file(tmp_log_dir):
    out = json.loads(tools.save_learning_log("LoRAの復習", "Aは小さく、Bはゼロで初期化する。", 2))
    assert out["saved"] is True
    files = list(tmp_log_dir.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "lecture: 2" in text and "# LoRAの復習" in text and "Bはゼロ" in text


def test_same_content_is_saved_only_once(tmp_log_dir):
    """Reintento (p. ej., tras un corte de conexión) → no se duplica: idempotencia."""
    first = json.loads(tools.save_learning_log("同じ記録", "本文", 3))
    second = json.loads(tools.save_learning_log("同じ記録", "本文", 3))
    assert first["saved"] is True
    assert second["saved"] is False and second["already_exists"] is True
    assert len(list(tmp_log_dir.glob("*.md"))) == 1


@pytest.mark.parametrize("title", ["../../etc/passwd", "/tmp/evil", "..\\..\\x", "a/b/c"])
def test_title_cannot_escape_log_dir(tmp_log_dir, title):
    """El título lo escribe el modelo: no debe poder elegir la ruta (frontera de confianza)."""
    out = json.loads(tools.save_learning_log(title, "本文", 1))
    assert out["saved"] is True
    for f in tmp_log_dir.parent.rglob("*.md"):
        assert f.parent == tmp_log_dir


@pytest.mark.parametrize(
    "title,content,lecture",
    [("", "本文", 1), ("題", "   ", 1), ("x" * 81, "本文", 1), ("題", "x" * 2001, 1), ("題", "本文", 14), ("題", "本文", -1)],
)
def test_invalid_arguments_are_rejected_without_writing(tmp_log_dir, title, content, lecture):
    out = json.loads(tools.save_learning_log(title, content, lecture))
    assert out["saved"] is False and out["reason"]
    assert not tmp_log_dir.exists() or not list(tmp_log_dir.iterdir())


def test_prepare_is_deterministic():
    """Mismo contenido → mismo id; lo que se aprueba es exactamente lo que se escribe."""
    now = datetime(2026, 11, 16, 10, 0)
    a = tools.prepare_learning_log("題", "本文", 3, now=now)
    b = tools.prepare_learning_log("題", "本文", 3, now=now)
    assert a == b and a.path.name.startswith("2026-11-16_")


def test_make_quiz_handles_missing_lecture():
    assert "ありません" in tools.make_quiz(0)
    q = json.loads(tools.make_quiz(2))
    assert q["question"] and q["answer"]


# --- flujo de aprobación con el agente real (modelo falso) ------------------------


def _run(approver):
    model = TestModel(call_tools=["save_learning_log"], custom_output_text="完了")
    return agent_module.run_with_approval(agent_module.agent, "学習ログに保存して", model, approver=approver)


def test_tool_waits_for_approval_and_does_not_run_before(tmp_log_dir):
    seen = []

    def approver(call: ToolCallPart):
        seen.append(call.tool_name)
        assert not tmp_log_dir.exists() or not list(tmp_log_dir.iterdir())  # todavía no se escribió nada
        return True

    _run(approver)
    assert seen == ["save_learning_log"]


def test_approved_call_writes_file(tmp_log_dir):
    outcome = _run(lambda call: True)
    assert outcome.approval_rounds == 1 and not outcome.stopped_by_limit
    assert len(list(tmp_log_dir.glob("*.md"))) == 1
    returns = [p for m in outcome.result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    assert any(p.tool_name == "save_learning_log" and '"saved": true' in str(p.content) for p in returns)
    assert outcome.usage.requests >= 2  # la pausa de aprobación cuesta una llamada extra al LLM


def test_denied_call_writes_nothing_and_model_is_told(tmp_log_dir):
    outcome = _run(lambda call: ToolDenied("利用者が拒否"))
    assert not tmp_log_dir.exists() or not list(tmp_log_dir.iterdir())
    returns = [p for m in outcome.result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    assert any("利用者が拒否" in str(p.content) for p in returns)


def test_cli_approver_defaults_to_no():
    call = ToolCallPart("save_learning_log", {"title": "題", "content": "本文", "lecture": 1})
    assert isinstance(agent_module.cli_approver(call, input_fn=lambda _: "", interactive=True), ToolDenied)
    assert isinstance(agent_module.cli_approver(call, input_fn=lambda _: "n", interactive=True), ToolDenied)
    assert agent_module.cli_approver(call, input_fn=lambda _: "y", interactive=True) is True


def test_cli_approver_denies_when_not_interactive():
    call = ToolCallPart("save_learning_log", {"title": "題", "content": "本文", "lecture": 1})
    assert isinstance(agent_module.cli_approver(call, interactive=False), ToolDenied)


def test_cli_approver_rejects_invalid_args_without_asking():
    call = ToolCallPart("save_learning_log", {"title": "", "content": "本文", "lecture": 1})

    def must_not_ask(_):
        raise AssertionError("no se debe pedir aprobación para argumentos inválidos")

    assert isinstance(agent_module.cli_approver(call, input_fn=must_not_ask, interactive=True), ToolDenied)


def test_approval_rounds_are_capped(monkeypatch):
    """Si el modelo pidiera aprobación sin fin, el harness corta (condición de parada externa)."""
    outcome = agent_module.run_with_approval(
        agent_module.agent, "保存して", TestModel(call_tools=["save_learning_log"]),
        approver=lambda call: True, max_rounds=0,
    )
    assert outcome.stopped_by_limit


def test_cli_approver_treats_ctrl_c_and_ctrl_d_as_no():
    call = ToolCallPart("save_learning_log", {"title": "題", "content": "本文", "lecture": 1})
    for exc in (EOFError, KeyboardInterrupt):
        def boom(_, exc=exc):
            raise exc
        assert isinstance(agent_module.cli_approver(call, input_fn=boom, interactive=True), ToolDenied)
