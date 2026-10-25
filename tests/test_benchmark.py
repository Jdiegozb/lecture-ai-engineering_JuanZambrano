"""第1回 発展課題のテスト（APIキー不要。偽のクライアントで LLM を呼ばない）。"""

import csv
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from google.genai import errors, types

from app.ask import build_config, format_usage

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts" / "benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
sys.modules["benchmark"] = benchmark  # dataclass が自分のモジュールを参照するため
spec.loader.exec_module(benchmark)


class FakeModels:
    """1回目の呼び出しだけ 429 を返し、あとは固定のトークン数で答える。"""

    def __init__(self):
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append((model, contents, config))
        if len(self.calls) == 1:
            raise errors.ClientError(429, {"error": {"message": "rate limit", "status": "RESOURCE_EXHAUSTED"}})
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=20, thoughts_token_count=5, total_token_count=35
        )
        return SimpleNamespace(text=f"respuesta de {model}", usage_metadata=usage)


def test_format_usage_shows_thoughts():
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=7, candidates_token_count=11, thoughts_token_count=3, total_token_count=21
    )
    assert format_usage(usage) == "[tokens] 入力 7 / 出力 11 / 思考 3 / 合計 21"
    assert "取得できません" in format_usage(None)


def test_build_config_only_when_temperature_given():
    assert build_config(None) is None
    assert build_config(0.0).temperature == 0.0


def test_benchmark_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    monkeypatch.setattr(benchmark.time, "sleep", lambda s: None)
    fake = FakeModels()
    client = SimpleNamespace(models=fake)

    calls = benchmark.main(
        ["--models", "m1,m2", "--questions", "lora", "--temperatures", "none,0",
         "--reps", "2", "--tag", "t", "--rpm", "15", "--rpd", "1000"],
        client=client,
    )

    # 2 モデル × 1 質問 × 2 T × 2 回 = 8 件。1件目は 429 → 再試行で ok
    assert len(calls) == 8
    assert calls[0].status == "ok (tras 429)"
    assert all(c.status.startswith("ok") for c in calls)
    assert calls[0].output_tok_per_s is not None
    # モデルを交互に呼んでいる（m1, m2, m1, m2, ...）
    assert [c.model for c in calls[:4]] == ["m1", "m2", "m1", "m2"]
    # temperature=0 のときだけ config が渡る
    assert any(cfg is not None and cfg.temperature == 0 for _, _, cfg in fake.calls)

    out = tmp_path / "lectures" / "01" / "results" / "t"
    rows = list(csv.DictReader(open(out / "calls.csv", encoding="utf-8")))
    assert len(rows) == 8 and rows[1]["total_tokens"] == "35"
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "| m1 | lora | default | 2/2 |" in summary
    assert "respuestas 429: 1" in summary
    assert "RPM 15" in summary
    assert "respuesta de m2" in (out / "answers.md").read_text(encoding="utf-8")
