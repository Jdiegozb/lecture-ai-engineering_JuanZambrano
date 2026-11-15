"""第2回 宿題（発展）: 評価セット・v2 学習データ・検索ベースラインを作る（Codespaces で実行）。

Uso:
    # 1) datos de entrenamiento v1 (script del curso, sin cambios)
    uv run python scripts/make_sft_dataset.py > glossary_sft.jsonl

    # 2) set de evaluación + baseline de búsqueda (no llama a ninguna API)
    uv run python scripts/make_glossary_data.py eval --out glossary_eval.jsonl
    uv run python scripts/make_glossary_data.py search-baseline --eval glossary_eval.jsonl

    # 3) (opcional) datos v2: v1 + paráfrasis + ejemplos negativos
    uv run python scripts/make_glossary_data.py sft-v2 --out glossary_sft_v2.jsonl

Sube a Colab: glossary_sft.jsonl, glossary_eval.jsonl, data/glossary.json y scripts/glossary_ft.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import glossary_ft as gft  # noqa: E402

DEFAULT_GLOSSARY = ROOT / "data" / "glossary.json"


def cmd_eval(args) -> None:
    glossary = gft.load_glossary(args.glossary)
    items = gft.build_eval_items(glossary)
    leaks = gft.check_no_leak(gft.build_sft_records(glossary, "v2"), items)
    clash = gft.check_absent_terms(glossary)
    if leaks or clash:
        sys.exit(f"Set de evaluación inválido. fuga={leaks} términos_presentes={clash}")
    gft.write_jsonl(items, args.out)
    counts = {c: sum(i["category"] == c for i in items) for c in gft.CATEGORY_ORDER}
    print(f"{len(items)} preguntas → {args.out}  {counts}", file=sys.stderr)


def cmd_sft_v2(args) -> None:
    records = gft.build_sft_records(gft.load_glossary(args.glossary), "v2")
    gft.write_jsonl(records, args.out)
    print(f"{len(records)} ejemplos → {args.out}", file=sys.stderr)


def cmd_search_baseline(args) -> None:
    glossary = gft.load_glossary(args.glossary)
    items = gft.read_jsonl(args.eval)
    rows = [gft.score_output(it, gft.search_answer(it["question"], glossary), glossary) for it in items]
    summary = gft.summarize(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                                  encoding="utf-8")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--glossary", default=str(DEFAULT_GLOSSARY))
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval", help="set de evaluación (JSONL)")
    e.add_argument("--out", default="glossary_eval.jsonl")
    e.set_defaults(func=cmd_eval)
    v = sub.add_parser("sft-v2", help="datos de entrenamiento v2 (JSONL, formato messages)")
    v.add_argument("--out", default="glossary_sft_v2.jsonl")
    v.set_defaults(func=cmd_sft_v2)
    s = sub.add_parser("search-baseline", help="puntúa la búsqueda pura en el glosario")
    s.add_argument("--eval", default="glossary_eval.jsonl")
    s.add_argument("--out", default="eval_search.json")
    s.set_defaults(func=cmd_search_baseline)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
