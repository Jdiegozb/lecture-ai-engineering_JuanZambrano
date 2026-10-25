"""第1回 発展課題: 応答時間とトークン数を計測し、モデル・質問・temperature で比較する。

使い方（Codespaces のターミナルで）:
    # 発展: 3モデル × 3質問 × 3回 = 27 回の呼び出し
    uv run python scripts/benchmark.py --tag modelos

    # 基礎: 同じ質問を temperature を変えて3回ずつ（1モデル × 1質問 × 3 temperature × 3回 = 9 回）
    uv run python scripts/benchmark.py --tag temperature \
        --models gemini-3.5-flash-lite --questions curso --temperatures 0,1,2

結果は lectures/01/results/<tag>/ に出る:
    calls.csv    呼び出し1回ごとの計測値（生データ）
    answers.md   回答本文（同じ質問への回答の違いを見る用）
    summary.md   集計表と、無料枠のレート制限から見た試算

設計メモ:
- 時間帯による API の混み具合の偏りを減らすため、ループは「回 → 質問 → モデル」の順にして
  モデルを交互に呼ぶ（モデルAを全部終えてからモデルB、にはしない）。
- 応答時間は time.perf_counter() で generate_content の前後を測る（ネットワーク往復を含む）。
- 429（レート制限）は失敗として記録し、待ってから1回だけ再試行する。
  何回 429 が出たかも、無料枠との関係を考察する材料になる。
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from google import genai
from google.genai import errors, types

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ask import DEFAULT_QUESTION, build_config  # noqa: E402
from app.config import get_api_key  # noqa: E402

# 性質の違う3つの質問: 短い一般知識 / 講座固有（モデルが知らない） / 長い出力
QUESTIONS = {
    "lora": "LoRAとは何ですか？",
    "curso": DEFAULT_QUESTION,
    "largo": "Transformerの自己注意機構を、数式を使って詳しく説明してください。",
}
DEFAULT_MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite"]


@dataclass
class Call:
    rep: int
    question_id: str
    model: str
    temperature: str
    status: str  # ok / エラーコード
    latency_s: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thought_tokens: int | None = None
    total_tokens: int | None = None
    output_tok_per_s: float | None = None  # (出力 + 思考) / 応答時間
    answer_chars: int | None = None
    answer: str = ""


def call_once(client, model: str, question: str, temperature: float | None) -> tuple[float, object]:
    start = time.perf_counter()
    response = client.models.generate_content(
        model=model, contents=question, config=build_config(temperature)
    )
    return time.perf_counter() - start, response


def measure(client, rep, qid, model, temperature, wait_429: float, retried=False) -> Call:
    temp_label = "default" if temperature is None else f"{temperature:g}"
    try:
        latency, response = call_once(client, model, QUESTIONS[qid], temperature)
    except errors.APIError as e:
        if e.code == 429 and not retried:
            print(f"    429 → {wait_429:.0f}s 待って再試行")
            time.sleep(wait_429)
            call = measure(client, rep, qid, model, temperature, wait_429, retried=True)
            call.status = f"{call.status} (tras 429)"
            return call
        return Call(rep, qid, model, temp_label, status=str(e.code))

    u = response.usage_metadata
    prompt = (u.prompt_token_count or 0) if u else None
    output = (u.candidates_token_count or 0) if u else None
    thoughts = (u.thoughts_token_count or 0) if u else None
    total = (u.total_token_count or 0) if u else None
    text = response.text or ""
    generated = (output or 0) + (thoughts or 0)
    return Call(
        rep, qid, model, temp_label, status="ok",
        latency_s=round(latency, 3),
        prompt_tokens=prompt, output_tokens=output, thought_tokens=thoughts,
        total_tokens=total,
        output_tok_per_s=round(generated / latency, 1) if latency > 0 else None,
        answer_chars=len(text), answer=text,
    )


def run(client, models, question_ids, temperatures, reps, sleep_s, wait_429) -> list[Call]:
    calls: list[Call] = []
    plan = [(r, q, t, m) for r in range(1, reps + 1) for q in question_ids
            for t in temperatures for m in models]
    for i, (rep, qid, temp, model) in enumerate(plan, 1):
        call = measure(client, rep, qid, model, temp, wait_429)
        calls.append(call)
        info = (f"{call.latency_s:.2f}s, {call.total_tokens} tok" if call.status.startswith("ok")
                else f"ERROR {call.status}")
        print(f"[{i}/{len(plan)}] rep{rep} {qid:<6} {model:<24} T={call.temperature:<7} {info}")
        if i < len(plan):
            time.sleep(sleep_s)  # 1分あたりの上限（RPM）に当たらないよう間隔をあける
    return calls


# ---------- 出力 ----------

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 1) if xs else None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def summarize(calls: list[Call]) -> list[dict]:
    groups: dict[tuple, list[Call]] = {}
    for c in calls:
        groups.setdefault((c.model, c.question_id, c.temperature), []).append(c)
    rows = []
    for (model, qid, temp), cs in groups.items():
        ok = [c for c in cs if c.status.startswith("ok")]
        lat = [c.latency_s for c in ok]
        rows.append({
            "modelo": model, "pregunta": qid, "T": temp,
            "ok/n": f"{len(ok)}/{len(cs)}",
            "lat. mediana (s)": _median(lat),
            "lat. min–max (s)": f"{min(lat):.2f}–{max(lat):.2f}" if lat else "-",
            "entrada": _mean(c.prompt_tokens for c in ok),
            "salida": _mean(c.output_tokens for c in ok),
            "pensamiento": _mean(c.thought_tokens for c in ok),
            "total": _mean(c.total_tokens for c in ok),
            "tok/s": _mean(c.output_tok_per_s for c in ok),
            "caracteres": _mean(c.answer_chars for c in ok),
        })
    return rows


def md_table(rows: list[dict]) -> str:
    if not rows:
        return "(sin datos)\n"
    head = list(rows[0])
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join("-" if r[h] is None else str(r[h]) for h in head) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def quota_section(calls: list[Call], args) -> str:
    ok = [c for c in calls if c.status.startswith("ok")]
    n429 = sum("429" in c.status for c in calls)
    max_tok = max((c.total_tokens or 0) for c in ok) if ok else 0
    mean_tok = _mean(c.total_tokens for c in ok) or 0
    lines = [
        "## Relación con la cuota gratuita\n",
        f"- Llamadas realizadas: {len(calls)} (ok: {len(ok)}, respuestas 429: {n429})",
        f"- Pausa entre llamadas: {args.sleep:g} s → ritmo máximo ≈ {60 / max(args.sleep, 0.01):.0f} llamadas/min "
        "(sin contar la latencia)",
        f"- Tokens por llamada: media {mean_tok:g}, máximo {max_tok}",
    ]
    if args.rpm or args.tpm or args.rpd:
        lines.append("\nLímites usados para el cálculo (consultados en AI Studio / página de rate limits):\n")
        if args.rpm:
            lines.append(f"- RPM {args.rpm}: con 1 llamada por pregunta caben {args.rpm} preguntas/min; "
                         "un agente que hace ~4 llamadas por pregunta, solo ~"
                         f"{args.rpm // 4} preguntas/min")
        if args.tpm and mean_tok:
            lines.append(f"- TPM {args.tpm}: con {mean_tok:g} tokens/llamada de media caben "
                         f"~{int(args.tpm // mean_tok)} llamadas/min antes de chocar con el límite de tokens")
        if args.rpd:
            lines.append(f"- RPD {args.rpd}: esta medición consumió {len(calls)} llamadas = "
                         f"{100 * len(calls) / args.rpd:.0f} % del cupo diario")
    else:
        lines.append("\n(Pasa --rpm/--tpm/--rpd con los límites de tu cuenta para que se calcule el margen.)")
    return "\n".join(lines) + "\n"


def write_outputs(calls: list[Call], out_dir: Path, args) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "calls.csv", "w", newline="", encoding="utf-8") as f:
        cols = [fl.name for fl in fields(Call) if fl.name != "answer"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for c in calls:
            d = asdict(c)
            d.pop("answer")
            w.writerow(d)

    with open(out_dir / "answers.md", "w", encoding="utf-8") as f:
        f.write(f"# Respuestas ({args.tag})\n")
        for qid in dict.fromkeys(c.question_id for c in calls):
            f.write(f"\n## Pregunta `{qid}`: {QUESTIONS[qid]}\n")
            for c in (c for c in calls if c.question_id == qid):
                f.write(f"\n### {c.model} · T={c.temperature} · rep {c.rep} · {c.status}\n\n")
                f.write((c.answer.strip() or "(sin respuesta)") + "\n")

    with open(out_dir / "summary.md", "w", encoding="utf-8") as f:
        f.write(f"# Resumen de la medición ({args.tag})\n\n")
        f.write(f"Fecha: {time.strftime('%Y-%m-%d %H:%M %Z')} · repeticiones: {args.reps}\n\n")
        f.write(md_table(summarize(calls)))
        f.write("\n" + quota_section(calls, args))

    print(f"\nResultados en {out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir}/")


def parse_temperatures(s: str) -> list[float | None]:
    return [None if t.strip() in ("", "none", "default") else float(t) for t in s.split(",")]


def main(argv=None, client=None) -> list[Call]:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--questions", default=",".join(QUESTIONS), help=f"de: {', '.join(QUESTIONS)}")
    p.add_argument("--temperatures", default="none", help="ej. none o 0,1,2")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--sleep", type=float, default=5.0, help="segundos entre llamadas")
    p.add_argument("--wait-429", type=float, default=60.0)
    p.add_argument("--tag", default="run")
    p.add_argument("--rpm", type=int, help="límite de peticiones/min de tu cuenta (opcional)")
    p.add_argument("--tpm", type=int, help="límite de tokens/min (opcional)")
    p.add_argument("--rpd", type=int, help="límite de peticiones/día (opcional)")
    args = p.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    qids = [q.strip() for q in args.questions.split(",") if q.strip()]
    unknown = [q for q in qids if q not in QUESTIONS]
    if unknown:
        p.error(f"preguntas desconocidas: {unknown}")
    temps = parse_temperatures(args.temperatures)

    n = len(models) * len(qids) * len(temps) * args.reps
    print(f"Plan: {len(models)} modelos × {len(qids)} preguntas × {len(temps)} T × {args.reps} reps = {n} llamadas "
          f"(≈ {n * args.sleep / 60:.1f} min de pausas)\n")

    client = client or genai.Client(api_key=get_api_key())
    calls = run(client, models, qids, temps, args.reps, args.sleep, args.wait_429)
    write_outputs(calls, ROOT / "lectures" / "01" / "results" / args.tag, args)
    return calls


if __name__ == "__main__":
    main()
