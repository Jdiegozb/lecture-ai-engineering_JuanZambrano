"""第4回 宿題（実装）: comprobaciones por código y métricas para mi propio conjunto de evaluación.

Uso (sin API key; lee lo que ya generaron app.judge --generate y app.judge):
    uv run python -m app.eval_checks \
        --cases data/eval/my_cases.jsonl \
        --labels lectures/04/my_labels.jsonl \
        --judge lectures/04/my_judge_result.json \
        --out lectures/04/my_eval_report.json

Qué hace (Clase 4):
- Ejecuta los checks deterministas que cada caso declara en reference.checks (Parte 4: "lo que se puede
  comprobar, compruébalo con código"). Algunos miran el TEXTO (frases, regex, longitud, bloques de código) y
  otros la TRAZA que guardó app.judge --generate (herramientas pedidas, aprobaciones, archivos creados):
  lo que la agente HIZO, que el juez LLM no ve (Parte 3: GAUGE; Apéndice: "agentes: estado final y camino").
- Compara con las etiquetas humanas al juez LLM y a los checks de código, por criterio, con las métricas que
  la clase pide mirar además del acuerdo: recall de fallos, precisión de fallos y κ de Cohen.
- Calcula la línea base de la agente (tasa de aprobado según las etiquetas humanas) con su intervalo de
  confianza de Wilson al 95 %: con 10 casos el intervalo es enorme y hay que decirlo (Parte 2).
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from app.judge import ALL_CRITERIA, REQUIRED, ROOT, check_lecture_mark, load_labels, read_jsonl
from app import tools

# Criterios que puede cubrir un check de código. "behavior" no está en la rúbrica del curso:
# es lo que la agente hizo (herramientas, aprobación), que solo se ve en la traza.
CHECK_CRITERIA = [key for key, _ in ALL_CRITERIA] + ["behavior"]
NAMES = dict(ALL_CRITERIA) | {"behavior": "行動（ツール・承認）"}

PASS, FAIL, SKIP = "pass", "fail", "skip"
CODE_FENCE = re.compile(r"```")
CODE_BLOCK = re.compile(r"```.*?```", re.S)  # bloque completo (mismo patrón que app/judge.py)


# ---------------------------------------------------------------- checks (uno por tipo)
def _tool_names(trace: dict) -> list[str]:
    return [c["tool"] for c in trace.get("tool_calls", [])]


def _glossary_definitions_copied(answer: str) -> int:
    """Cuántas definiciones del glosario aparecen literalmente (≥ 40 caracteres) en la respuesta."""
    return sum(1 for e in tools.load_glossary() if e["definition"][:40] in answer)


def run_check(check: dict, case: dict) -> tuple[str, str]:
    """Ejecuta 1 check. Devuelve (pass|fail|skip, detalle). skip = falta la traza (respuesta sin generar aquí)."""
    answer = case.get("answer", "") or ""
    trace = case.get("trace")
    kind = check["type"]

    if kind in {"tool_called", "tool_not_called", "approval_requested"} and trace is None:
        return SKIP, "sin traza: genera las respuestas con app.judge --generate"

    if kind == "tool_called":
        names = _tool_names(trace)
        return (PASS if check["tool"] in names else FAIL), f"llamadas={names}"
    if kind == "tool_not_called":
        names = _tool_names(trace) + trace.get("approvals_requested", [])
        return (FAIL if check["tool"] in names else PASS), f"llamadas={names}"
    if kind == "approval_requested":
        asked = check["tool"] in trace.get("approvals_requested", [])
        created = trace.get("files_created", 0)
        ok = asked and created == 0
        return (PASS if ok else FAIL), f"aprobación pedida={asked}, archivos creados={created}"
    if kind == "contains_any":
        hit = next((t for t in check["texts"] if t in answer), None)
        return (PASS if hit else FAIL), f"encontrado={hit!r}"
    if kind == "not_contains":
        hit = next((t for t in check["texts"] if t in answer), None)
        return (FAIL if hit else PASS), f"encontrado={hit!r}"
    if kind == "not_regex":
        m = re.search(check["pattern"], answer)
        return (FAIL if m else PASS), f"coincidencia={m.group(0)!r}" if m else "sin coincidencia"
    if kind == "no_code_block":
        n = len(CODE_FENCE.findall(answer)) // 2
        return (FAIL if n else PASS), f"bloques de código={n}"
    if kind == "max_chars":
        body = CODE_BLOCK.sub("", answer).strip()
        return (PASS if len(body) <= check["n"] else FAIL), f"{len(body)} caracteres (máx. {check['n']})"
    if kind == "max_glossary_definitions":
        n = _glossary_definitions_copied(answer)
        return (PASS if n <= check["n"] else FAIL), f"definiciones copiadas={n} (máx. {check['n']})"
    raise ValueError(f"tipo de check desconocido: {kind}")


def run_case_checks(case: dict) -> list[dict]:
    """Todos los checks de un caso. "回の表示" se comprueba siempre, con la MISMA función que usa app.judge."""
    results = [{"type": "lecture_mark", "criterion": "lecture_mark", "verdict": check_lecture_mark(case.get("answer", "")),
                "detail": "末尾（最後の行）に「第N回」", "why": "回の表示（コード）"}]
    for check in case.get("reference", {}).get("checks", []):
        if check.get("criterion") not in CHECK_CRITERIA:
            raise ValueError(f"#{case['id']}: criterion desconocido {check.get('criterion')!r}")
        verdict, detail = run_check(check, case)
        results.append({"type": check["type"], "criterion": check["criterion"], "verdict": verdict,
                        "detail": detail, "why": check.get("why", "")})
    return results


def code_verdicts(results: list[dict]) -> dict[str, str]:
    """Veredicto de código por criterio: fail si algún check de ese criterio falla; pass si alguno pasó y ninguno falló."""
    out: dict[str, str] = {}
    for r in results:
        if r["verdict"] == SKIP:
            continue
        if r["verdict"] == FAIL or out.get(r["criterion"]) == FAIL:
            out[r["criterion"]] = FAIL
        else:
            out[r["criterion"]] = PASS
    return out


# ---------------------------------------------------------------- métricas (el "fallo" es la clase positiva)
def confusion(pairs: list[tuple[str, str]]) -> dict[str, int]:
    """pairs = [(humano, predicho)] con valores pass/fail. Positivo = fail (lo que queremos detectar)."""
    c = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    for human, pred in pairs:
        if human == FAIL:
            c["tp" if pred == FAIL else "fn"] += 1
        else:
            c["fp" if pred == FAIL else "tn"] += 1
    return c


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def cohen_kappa(c: dict[str, int]) -> float | None:
    """κ = (p_o − p_e) / (1 − p_e). None si no está definido (p. ej., todos iguales: p_e = 1)."""
    n = sum(c.values())
    if not n:
        return None
    p_o = (c["tp"] + c["tn"]) / n
    human_fail = (c["tp"] + c["fn"]) / n
    pred_fail = (c["tp"] + c["fp"]) / n
    p_e = human_fail * pred_fail + (1 - human_fail) * (1 - pred_fail)
    return None if math.isclose(p_e, 1.0) else (p_o - p_e) / (1 - p_e)


def grader_metrics(pairs: list[tuple[str, str]]) -> dict:
    c = confusion(pairs)
    n = sum(c.values())
    return {
        "n": n,
        "agreement": _ratio(c["tp"] + c["tn"], n),
        "human_fails": c["tp"] + c["fn"],
        "recall_fail": _ratio(c["tp"], c["tp"] + c["fn"]),  # de los fallos humanos, cuántos detectó
        "precision_fail": _ratio(c["tp"], c["tp"] + c["fp"]),  # de sus "fail", cuántos eran fallos
        "kappa": cohen_kappa(c),
        "confusion": c,
    }


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Intervalo de Wilson (95 %). Mejor que p ± z·√(p(1−p)/n) con n pequeño o p cerca de 0 o 1."""
    if not n:
        return None
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, center - half), min(1.0, center + half)


# ---------------------------------------------------------------- informe
def build_report(cases: list[dict], labels: dict[str, dict], judge_result: dict | None) -> dict:
    per_case = {c["id"]: run_case_checks(c) for c in cases}
    code_by_case = {cid: code_verdicts(res) for cid, res in per_case.items()}
    judge_v = (judge_result or {}).get("verdicts", {})
    labeled = [c["id"] for c in cases if c["id"] in labels]

    criteria = {}
    for key, name in ALL_CRITERIA:
        llm_pairs, code_pairs = [], []
        for cid in labeled:
            human = labels[cid].get(key)
            if human not in (PASS, FAIL):
                continue
            j = judge_v.get(cid, {}).get(key, {}).get("verdict")
            if j in (PASS, FAIL) and key != "lecture_mark":
                llm_pairs.append((human, j))
            cv = code_by_case[cid].get(key)
            if cv:
                code_pairs.append((human, cv))
        criteria[key] = {"name": name, "llm": grader_metrics(llm_pairs) if llm_pairs else None,
                         "code": grader_metrics(code_pairs) if code_pairs else None}

    # Línea base: tasa de aprobado de la agente según las ETIQUETAS HUMANAS (el estándar), con su IC
    overall_pass = sum(1 for cid in labeled if all(labels[cid].get(k) == PASS for k in REQUIRED))
    behavior = [v["behavior"] for v in code_by_case.values() if "behavior" in v]
    traces = [c["trace"] for c in cases if c.get("trace")]

    def mean(field):
        vals = [t[field] for t in traces if t.get(field) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "n_cases": len(cases),
        "n_labeled": len(labeled),
        "baseline": {
            "overall_pass": overall_pass,
            "overall_pass_rate": _ratio(overall_pass, len(labeled)),
            "wilson95": wilson_interval(overall_pass, len(labeled)),
            "behavior_pass": sum(v == PASS for v in behavior),
            "behavior_checked": len(behavior),
            "mean_requests": mean("requests"),
            "mean_elapsed_s": mean("elapsed_s"),
        },
        "criteria": criteria,
        "per_case": per_case,
        "code_by_case": code_by_case,
    }


def _fmt(x: float | None, pct: bool = True) -> str:
    if x is None:
        return "—"
    return f"{100 * x:.0f}%" if pct else f"{x:.2f}"


def print_report(rep: dict) -> None:
    b = rep["baseline"]
    lo_hi = b["wilson95"]
    ci = f"IC95 {_fmt(lo_hi[0])}–{_fmt(lo_hi[1])}" if lo_hi else ""
    print(f"\nLínea base (etiquetas humanas, criterios obligatorios): {b['overall_pass']}/{rep['n_labeled']} "
          f"= {_fmt(b['overall_pass_rate'])}  {ci}")
    print(f"Comportamiento (código, traza): {b['behavior_pass']}/{b['behavior_checked']} casos sin fallos   "
          f"requests medios={b['mean_requests']}  tiempo medio={b['mean_elapsed_s']} s")

    print("\nPor criterio: humano vs juez LLM / humano vs código   (positivo = fail)")
    print(f"  {'criterio':<14}{'quién':<6}{'n':>3} {'acuerdo':>8} {'fallos':>7} {'recall':>7} {'precis.':>8} {'κ':>6}")
    for key, row in rep["criteria"].items():
        for who in ("llm", "code"):
            m = row[who]
            if not m:
                continue
            print(f"  {key:<14}{who:<6}{m['n']:>3} {_fmt(m['agreement']):>8} {m['human_fails']:>7} "
                  f"{_fmt(m['recall_fail']):>7} {_fmt(m['precision_fail']):>8} {_fmt(m['kappa'], pct=False):>6}")

    print("\nChecks de código por caso (solo los que fallan o se omiten)")
    for cid, results in rep["per_case"].items():
        for r in results:
            if r["verdict"] != PASS:
                print(f"  #{cid} {r['criterion']:<12} {r['type']:<22} {r['verdict']:<4}  {r['detail']}  ← {r['why']}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Checks por código y métricas del propio conjunto de evaluación")
    p.add_argument("--cases", type=Path, default=ROOT / "data" / "eval" / "my_cases.jsonl")
    p.add_argument("--labels", type=Path, default=ROOT / "lectures" / "04" / "my_labels.jsonl")
    p.add_argument("--judge", type=Path, default=ROOT / "lectures" / "04" / "my_judge_result.json",
                   help="salida de app.judge (opcional: sin ella solo se informan los checks de código)")
    p.add_argument("--out", type=Path, default=ROOT / "lectures" / "04" / "my_eval_report.json")
    args = p.parse_args(argv)

    cases = read_jsonl(args.cases)
    if not args.labels.exists():
        raise SystemExit(f"{args.labels} no existe: etiqueta primero con tools/annotate.py")
    labels = load_labels(args.labels)
    judge_result = json.loads(args.judge.read_text(encoding="utf-8")) if args.judge.exists() else None
    if judge_result is None:
        print(f"[aviso] {args.judge} no existe: se omite la comparación con el juez LLM")

    rep = build_report(cases, labels, judge_result)
    print_report(rep)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {args.out} に保存しました")


if __name__ == "__main__":
    main()
