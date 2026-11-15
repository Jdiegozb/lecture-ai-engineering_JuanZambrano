"""第2回 宿題（発展）: 用語集で LoRA 学習したモデルを評価するための共通部品。

標準ライブラリだけで動く（Colab にもそのままアップロードして import できる）。

    datos de entrenamiento  build_sft_records(glossary, variant="v1" | "v2")
    set de evaluación       build_eval_items(glossary)
    búsqueda en glosario    lookup(question, glossary)   ← baseline "sistema que busca"
    puntuación              score_output(item, output, glossary) / summarize(rows)

Diseño de la evaluación (5 categorías + 2 de control):
    seen        mismo enunciado que en el entrenamiento (fuga intencional: mide memorización)
    reworded    mismo término, plantilla nueva
    alias       el término escrito con un alias (el entrenamiento solo usa el nombre principal)
    natural     pregunta natural sin la plantilla, p. ej. la pregunta de la Clase 1
    fictional   término inventado → lo correcto es decir que no está en el glosario
    absent_real término real de IA que NO está en el glosario → control de "contaminación"
    general     pregunta ajena al glosario → control de olvido / sobreajuste
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Datos de entrenamiento
# ---------------------------------------------------------------------------

# Plantillas de scripts/make_sft_dataset.py (v1). Se copian tal cual para poder
# verificar que el JSONL subido a Colab es idéntico al que genera el script.
V1_TEMPLATES = ["「{term}」とは何ですか？", "{term}について簡単に説明してください。"]

# v2 (opcional): más paráfrasis + ejemplos negativos. Las plantillas NO se repiten
# en la evaluación (ver EVAL_TEMPLATES) para no mezclar memorización con generalización.
V2_EXTRA_TEMPLATES = ["{term}の定義を教えてください。", "{term}とはどういう意味ですか？"]
REFUSAL_ANSWER = "「{term}」は講座の用語集に記載がありません。確認が必要です。"
# Términos inventados SOLO para entrenar la negativa (distintos de EVAL_FICTIONAL)
V2_NEGATIVE_TERMS = [
    "クロスモーダル剪定", "セマンティック・ハッシュチェーン", "逆温度サンプリング", "LoRAミラーリング",
    "トークン再帰圧縮", "エージェント・ブリッジ学習", "多段プロンプト融合", "勾配シャドーイング",
    "AIE2026の第15回演習", "MCPリレー認証",
]


def load_glossary(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["terms"]


def _chat(question: str, answer: str) -> dict:
    return {"messages": [{"role": "user", "content": question},
                         {"role": "assistant", "content": answer}]}


def build_sft_records(glossary: list[dict], variant: str = "v1") -> list[dict]:
    """v1 = exactamente lo que produce make_sft_dataset.py. v2 = v1 + paráfrasis + negativos."""
    if variant not in ("v1", "v2"):
        raise ValueError(f"variant desconocida: {variant}")
    records = [_chat(tpl.format(term=t["term"]), t["definition"])
               for t in glossary for tpl in V1_TEMPLATES]
    if variant == "v2":
        records += [_chat(tpl.format(term=t["term"]), t["definition"])
                    for t in glossary for tpl in V2_EXTRA_TEMPLATES]
        records += [_chat(tpl.format(term=term), REFUSAL_ANSWER.format(term=term))
                    for term in V2_NEGATIVE_TERMS for tpl in V1_TEMPLATES]
    return records


def read_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(records: list[dict], path: str | Path) -> None:
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


# ---------------------------------------------------------------------------
# Set de evaluación
# ---------------------------------------------------------------------------

# Términos evaluados y "palabras clave" que debe contener una respuesta correcta.
# Cada grupo es una lista de sinónimos (basta uno); todos los grupos son obligatorios.
# Se eligen conceptos, no la redacción exacta del glosario, para no castigar una
# respuesta correcta que viene del preentrenamiento.
EVAL_TERMS: dict[str, dict] = {
    # --- conocimiento general (el modelo base puede saberlo) ---
    "lora":           {"kind": "general", "keywords": [["低ランク", "low-rank", "ランク"], ["固定", "凍結", "フリーズ", "変更せず", "変えず"]]},
    "temperature":    {"kind": "general", "keywords": [["ランダム", "多様", "ばらつき", "確率"]]},
    "hallucination":  {"kind": "general", "keywords": [["事実と異なる", "存在しない", "誤った", "間違った", "事実ではない", "事実でない", "虚偽"]]},
    "token":          {"kind": "general", "keywords": [["単位"]]},
    "context-window": {"kind": "general", "keywords": [["上限", "最大", "限界"], ["トークン"]]},
    "overfitting":    {"kind": "general", "keywords": [["学習データ", "訓練データ", "トレーニングデータ"], ["未知", "新しい", "汎化", "テスト", "検証"]]},
    "quantization":   {"kind": "general", "keywords": [["ビット", "bit"], ["メモリ", "軽量", "削減", "減ら", "小さく"]]},
    "peft":           {"kind": "general", "keywords": [["一部", "少数", "小さな", "少ない", "ごく"], ["パラメータ"]]},
    "fine-tuning":    {"kind": "general", "keywords": [["追加", "再学習", "さらに"], ["学習"]]},
    "epoch":          {"kind": "general", "keywords": [["1周", "一周", "全体", "すべて", "全て", "1回"]]},
    # --- específicos del curso (el modelo base NO puede saberlo) ---
    "homework-levels":   {"kind": "course", "keywords": [["基礎"], ["実装"], ["発展"], ["1つ", "一つ", "どれか"]]},
    "default-model":     {"kind": "course", "keywords": [["gemini-3.5-flash-lite"]]},
    "codespaces-secret": {"kind": "course", "keywords": [["環境変数"], ["Codespaces", "コードスペース"]]},
    "api-key":           {"kind": "course", "keywords": [["秘密"], ["GEMINI_API_KEY", "Codespaces secret", "Codespaces"]]},
    "answer-md":         {"kind": "course", "keywords": [["提出"], ["PR", "プルリクエスト"]]},
    "lec-start-tag":     {"kind": "course", "keywords": [["タグ"], ["開始", "始め", "演習"]]},
}

SEEN_IDS = ["lora", "temperature", "hallucination", "token", "overfitting",
            "homework-levels", "default-model", "codespaces-secret"]
# Plantillas nuevas: no aparecen ni en v1 ni en v2.
EVAL_TEMPLATES = ["{term}の意味を、初心者にもわかるように教えてください。", "{term}って何のこと？"]
ALIAS_QUESTIONS = {  # id → alias (distinto del nombre principal, debe existir en el glosario)
    "lora": "Low-Rank Adaptation", "temperature": "温度パラメータ", "hallucination": "幻覚",
    "context-window": "コンテキスト長", "overfitting": "オーバーフィッティング", "fine-tuning": "追加学習",
    "homework-levels": "宿題レベル", "default-model": "デフォルトモデル",
    "codespaces-secret": "Codespacesのシークレット", "answer-md": "解答ファイル",
}
ALIAS_TEMPLATE = "{alias}について教えてください。"
NATURAL_QUESTIONS = {  # preguntas como las haría un estudiante; la primera es la de la Clase 1
    "AIE2026の講座の宿題にある「3レベル」とは何ですか？": "homework-levels",
    "この講座の演習で標準に使うモデルは何ですか？": "default-model",
    "APIキーはどこに保存して、どう読み込めばいいですか？": "api-key",
    "各回の演習の結果はどのファイルに書いて提出しますか？": "answer-md",
    "前の回が終わっていなくても、その回の演習を始めるにはどうすればいいですか？": "lec-start-tag",
}
EVAL_FICTIONAL = ["量子トークン圧縮", "ハイパーLoRAリング", "AIE2026の第14回の宿題",
                  "逆伝播エージェント蒸留", "スパイラル・プロンプト", "MCPフェデレーション署名"]
EVAL_ABSENT_REAL = ["RLHF", "知識蒸留", "Mixture of Experts", "ビームサーチ", "DPO", "RAG"]
EVAL_GENERAL = ["こんにちは。あなたは何ができますか？", "日本の首都はどこですか？",
                "Pythonでリストを逆順にするにはどうしますか？", "1から10までの整数の合計はいくつですか？"]


def build_eval_items(glossary: list[dict]) -> list[dict]:
    """Construye el set de evaluación. Omite (con aviso) ids que no estén en este glosario."""
    by_id = {t["id"]: t for t in glossary}
    items: list[dict] = []

    def add(category: str, question: str, term_id: str | None = None, **extra) -> None:
        items.append({"id": f"{category}-{len(items):02d}", "category": category,
                      "question": question, "term_id": term_id, **extra})

    missing = sorted(set(EVAL_TERMS) - set(by_id))
    if missing:
        print(f"[aviso] ids que no están en este glosario y se omiten: {missing}")

    for tid in SEEN_IDS:
        if tid in by_id:
            add("seen", V1_TEMPLATES[0].format(term=by_id[tid]["term"]), tid)
    for i, tid in enumerate(t for t in EVAL_TERMS if t in by_id):
        add("reworded", EVAL_TEMPLATES[i % len(EVAL_TEMPLATES)].format(term=by_id[tid]["term"]), tid)
    for tid, alias in ALIAS_QUESTIONS.items():
        if tid in by_id and alias in by_id[tid]["aliases"]:
            add("alias", ALIAS_TEMPLATE.format(alias=alias), tid)
    for q, tid in NATURAL_QUESTIONS.items():
        if tid in by_id:
            add("natural", q, tid)
    for i, term in enumerate(EVAL_FICTIONAL):
        tpl = V1_TEMPLATES[0] if i % 2 == 0 else EVAL_TEMPLATES[1]  # la mitad con la plantilla entrenada
        add("fictional", tpl.format(term=term), None)
    for term in EVAL_ABSENT_REAL:
        add("absent_real", V1_TEMPLATES[0].format(term=term), None)
    for q in EVAL_GENERAL:
        add("general", q, None)

    for it in items:
        if it["term_id"]:
            it["kind"] = EVAL_TERMS[it["term_id"]]["kind"]
            it["keywords"] = EVAL_TERMS[it["term_id"]]["keywords"]
            it["reference"] = by_id[it["term_id"]]["definition"]
    return items


def check_no_leak(train_records: list[dict], eval_items: list[dict]) -> list[str]:
    """Preguntas de evaluación (salvo 'seen') que aparecen literalmente en el entrenamiento."""
    train_q = {r["messages"][0]["content"] for r in train_records}
    return [it["question"] for it in eval_items if it["category"] != "seen" and it["question"] in train_q]


def check_absent_terms(glossary: list[dict]) -> list[str]:
    """Términos de 'fictional'/'absent_real' que en realidad SÍ están en el glosario (debería ser [])."""
    names = {n for e in glossary for n, _ in _names(e)}
    return [t for t in EVAL_FICTIONAL + EVAL_ABSENT_REAL if _norm(t) in names]


# ---------------------------------------------------------------------------
# Búsqueda en el glosario (baseline "sistema que busca", sin LLM)
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    # Igual que app/tools.py (Clase 3): minúsculas y sin espacios
    return text.casefold().replace(" ", "").replace("　", "")


def _names(entry: dict) -> list[tuple[str, bool]]:
    """(nombre normalizado, es_ascii) para term, id, alias y las partes entre paréntesis.

    "LLM（大規模言語モデル）" → "llm（大規模言語モデル）", "llm", "大規模言語モデル"
    """
    raw = [entry["term"], entry["id"], *entry["aliases"]]
    for name in list(raw):
        raw += [p for p in re.split(r"[（）()/・]", name) if p.strip()]
    out = {}
    for name in raw:
        n = _norm(name)
        if len(n) >= 2:  # descarta alias de 1 carácter como "r"
            out[n] = n.isascii()
    return list(out.items())


def lookup(question: str, glossary: list[dict], k: int = 3) -> list[dict]:
    """Devuelve hasta k entradas cuyos nombres aparecen en la pregunta (coincidencia más larga primero).

    Los nombres ASCII se comparan como palabra completa para que "pi" no coincida con "pipeline".
    """
    q = _norm(question)
    scored = []
    for e in glossary:
        best = 0
        for n, is_ascii in _names(e):
            hit = (re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", q) if is_ascii else n in q)
            if hit:
                best = max(best, len(n))
        if best:
            scored.append((best, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:k]]


def search_answer(question: str, glossary: list[dict]) -> str:
    """Respuesta del sistema de búsqueda pura: la definición del primer resultado, o una negativa."""
    hits = lookup(question, glossary, k=1)
    return hits[0]["definition"] if hits else "用語集に記載がありません。確認が必要です。"


def rag_messages(question: str, glossary: list[dict], k: int = 3) -> list[dict]:
    """Mensajes para la condición RAG: misma pregunta + extracto del glosario en el system prompt."""
    hits = lookup(question, glossary, k=k)
    excerpt = "\n".join(f"- {e['term']}: {e['definition']}" for e in hits) or "（該当する用語はありません）"
    system = ("あなたは講座 AIE2026 の用語集アシスタントです。次の「用語集の抜粋」だけを根拠に、日本語で簡潔に答えてください。"
              "抜粋に無い用語については、推測せずに「用語集に記載がありません。確認が必要です。」と答えてください。\n\n"
              f"用語集の抜粋:\n{excerpt}")
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


# ---------------------------------------------------------------------------
# Puntuación
# ---------------------------------------------------------------------------

REFUSAL_PATTERNS = ["記載がありません", "記載はありません", "見つかりません", "わかりません", "分かりません",
                    "知りません", "存じません", "確認が必要", "情報がありません", "存在しません", "定義されていません"]
# Umbral de "contaminación": F1 de bigramas con alguna definición del glosario.
# Calibrado con calibrate_contamination(): por encima del máximo entre definiciones distintas.
CONTAMINATION_F1 = 0.45


def char_bigrams(text: str) -> Counter:
    s = re.sub(r"\s+", "", text)
    return Counter(s[i:i + 2] for i in range(len(s) - 1))


def bigram_f1(pred: str, ref: str) -> float:
    """F1 de bigramas de caracteres (sirve para japonés sin tokenizador)."""
    p, r = char_bigrams(pred), char_bigrams(ref)
    overlap = sum((p & r).values())
    if not overlap:
        return 0.0
    precision, recall = overlap / sum(p.values()), overlap / sum(r.values())
    return 2 * precision * recall / (precision + recall)


def keyword_ratio(text: str, keyword_groups: list[list[str]]) -> float:
    t = text.casefold()
    hits = sum(any(k.casefold() in t for k in group) for group in keyword_groups)
    return hits / len(keyword_groups)


def is_refusal(text: str) -> bool:
    return any(p in text for p in REFUSAL_PATTERNS)


def closest_definition(text: str, glossary: list[dict]) -> tuple[str, float]:
    best = max(glossary, key=lambda e: bigram_f1(text, e["definition"]))
    return best["id"], round(bigram_f1(text, best["definition"]), 3)


def score_output(item: dict, output: str, glossary: list[dict]) -> dict:
    """Clasifica una salida.

    Términos del glosario: correct (todas las palabras clave) / partial / wrong / refused.
    fictional:             refused (deseado) / hallucinated.
    absent_real y general: refused / contaminated (copia una definición del glosario) / ok.
    """
    closest_id, closest_f1 = closest_definition(output, glossary)
    row = {"id": item["id"], "category": item["category"], "question": item["question"],
           "term_id": item.get("term_id"), "output": output,
           "closest_def": closest_id, "closest_f1": closest_f1}
    if item.get("term_id"):
        kw = keyword_ratio(output, item["keywords"])
        row.update(kind=item["kind"], keyword_ratio=round(kw, 3),
                   ref_f1=round(bigram_f1(output, item["reference"]), 3))
        if kw == 1:
            row["verdict"] = "correct"
        elif is_refusal(output):
            row["verdict"] = "refused"
        else:
            row["verdict"] = "partial" if kw > 0 else "wrong"
    elif item["category"] == "fictional":
        row["verdict"] = "refused" if is_refusal(output) else "hallucinated"
    else:
        if is_refusal(output):
            row["verdict"] = "refused"
        elif closest_f1 >= CONTAMINATION_F1:
            row["verdict"] = "contaminated"
        else:
            row["verdict"] = "ok"
    return row


CATEGORY_ORDER = ["seen", "reworded", "alias", "natural", "fictional", "absent_real", "general"]


def summarize(rows: list[dict]) -> dict:
    """Resumen por categoría + métricas principales."""
    by_cat: dict[str, dict] = {}
    for cat in CATEGORY_ORDER:
        rs = [r for r in rows if r["category"] == cat]
        if not rs:
            continue
        counts = Counter(r["verdict"] for r in rs)
        entry = {"n": len(rs), **{k: counts[k] for k in sorted(counts)}}
        if "keyword_ratio" in rs[0]:
            entry["mean_keyword_ratio"] = round(statistics.mean(r["keyword_ratio"] for r in rs), 3)
            entry["mean_ref_f1"] = round(statistics.mean(r["ref_f1"] for r in rs), 3)
        by_cat[cat] = entry

    def rate(cats, verdict, kind=None):
        rs = [r for r in rows if r["category"] in cats and (kind is None or r.get("kind") == kind)]
        return round(sum(r["verdict"] == verdict for r in rs) / len(rs), 3) if rs else None

    unseen = ["reworded", "alias", "natural"]
    headline = {
        "acc_seen (memorización, con fuga)": rate(["seen"], "correct"),
        "acc_unseen (reworded+alias+natural)": rate(unseen, "correct"),
        "acc_unseen_general": rate(unseen, "correct", "general"),
        "acc_unseen_course": rate(unseen, "correct", "course"),
        "over_refusal_unseen": rate(unseen, "refused"),
        "fictional_refusal (↑ mejor)": rate(["fictional"], "refused"),
        "fictional_hallucination (↓ mejor)": rate(["fictional"], "hallucinated"),
        "contamination_controls (↓ mejor)": rate(["absent_real", "general"], "contaminated"),
    }
    return {"headline": headline, "by_category": by_cat}


def calibrate_contamination(glossary: list[dict]) -> dict:
    """Distribución del F1 entre definiciones DISTINTAS: el umbral debe quedar por encima."""
    defs = [e["definition"] for e in glossary]
    vals = sorted(bigram_f1(a, b) for i, a in enumerate(defs) for b in defs[i + 1:])
    return {"pairs": len(vals), "median": round(statistics.median(vals), 3),
            "p99": round(vals[int(0.99 * (len(vals) - 1))], 3), "max": round(vals[-1], 3)}
