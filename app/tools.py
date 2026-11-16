"""第3回: エージェントに持たせるツール。

ここに書いた関数の docstring と型ヒントが、そのままモデルへの「ツールの説明文」になる。
説明文を書き換えると、モデルがツールを使うかどうか・どんな引数で呼ぶかが変わる。
"""

import hashlib
import json
import os
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
MAX_RESULTS = 3

# --- 宿題（実装）: save_learning_log の設定 ---------------------------------
# Carpeta de destino. La decide el CÓDIGO, nunca el modelo (frontera de confianza, Clase 3 Parte 9).
# Se puede cambiar con la variable de entorno (los tests usan una carpeta temporal).
LEARNING_LOG_DIR = Path(os.getenv("AIE_LEARNING_LOG_DIR", REPO_ROOT / "learning_log"))
MAX_TITLE_CHARS = 80
MAX_CONTENT_CHARS = 2000
MAX_LECTURE = 13  # el curso tiene 13 sesiones; 0 = sin sesión concreta


@cache
def load_glossary() -> list[dict]:
    with open(DATA_DIR / "glossary.json", encoding="utf-8") as f:
        return json.load(f)["terms"]


def _normalize(text: str) -> str:
    return text.casefold().replace(" ", "").replace("　", "")


def _names(entry: dict) -> list[str]:
    return [_normalize(entry["term"]), _normalize(entry["id"])] + [
        _normalize(a) for a in entry["aliases"]
    ]


def search_glossary(query: str) -> str:
    """講座の用語集から用語を検索し、定義と、どの回で扱うかを返す。

    AIエンジニアリングの用語や、この講座（AIE2026）に固有の言葉について
    答える前に使うこと。query には調べたい用語を1つだけ入れる（例: "LoRA"）。
    """
    q = _normalize(query)
    if not q:
        return "検索語が空です。調べたい用語を1つ指定してください。"
    glossary = load_glossary()

    exact = [e for e in glossary if q in _names(e)]
    # 「r」のような短い別名が何にでも当たらないよう、名前側が短いものは除く
    partial = [
        e for e in glossary
        if e not in exact and any(q in n or (len(n) >= 3 and n in q) for n in _names(e))
    ]
    in_definition = [
        e for e in glossary
        if e not in exact and e not in partial and q in _normalize(e["definition"])
    ]
    hits = (exact + partial + in_definition)[:MAX_RESULTS]

    if not hits:
        return f"用語集に「{query}」は見つかりませんでした。"
    return json.dumps(
        [
            {
                "term": e["term"],
                "lecture": e["lecture"],
                "definition": e["definition"],
                "related": e["related"],
            }
            for e in hits
        ],
        ensure_ascii=False,
    )


def get_lecture_summary(lecture: int) -> str:
    """指定した回（1始まりの整数）の講義の要点を返す。

    「第3回では何を学ぶ？」のように、回の内容や関係を聞かれたときに使う。
    """
    path = DATA_DIR / "lectures" / f"{lecture:02d}.md"
    if not path.exists():
        available = sorted(p.stem for p in (DATA_DIR / "lectures").glob("*.md"))
        return f"第{lecture}回の要点はまだありません。用意されている回: {', '.join(available)}"
    return path.read_text(encoding="utf-8")


# --- 第3回 演習: make_quiz ---------------------------------------------------


def make_quiz(lecture: int) -> str:
    """指定した回（1始まりの整数）の用語を1つ選び、確認問題とその答えを返す。

    「第2回の確認問題を出して」のように、復習用の問題を求められたときに使う。
    """
    terms = [t for t in load_glossary() if t["lecture"] == lecture]
    if not terms:
        available = sorted({t["lecture"] for t in load_glossary()})
        return f"第{lecture}回の用語は用語集にありません。問題を作れる回: {', '.join(map(str, available))}"
    term = random.choice(terms)
    return json.dumps(
        {"question": f"「{term['term']}」の意味は？", "answer": term["definition"], "lecture": lecture},
        ensure_ascii=False,
    )


# --- 宿題（実装）: save_learning_log ------------------------------------------


@dataclass(frozen=True)
class LearningLogEntry:
    """Lo que se va a escribir y dónde. Se calcula ANTES de pedir aprobación,
    para que la persona apruebe exactamente el archivo y el contenido finales."""

    entry_id: str
    title: str
    content: str
    lecture: int
    path: Path
    markdown: str


def _slugify(text: str, max_len: int = 40) -> str:
    """Nombre de archivo seguro: solo letras/números (incluye japonés) y guiones.
    Elimina '/', '..', espacios, etc., así el modelo no puede elegir la ruta."""
    text = unicodedata.normalize("NFKC", text)
    slug = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE).strip("-_")
    return slug[:max_len] or "log"


def prepare_learning_log(title: str, content: str, lecture: int, now: datetime | None = None) -> LearningLogEntry:
    """Valida los argumentos y construye la entrada. Lanza ValueError si algo no es válido.

    La usan tanto la herramienta (al ejecutar) como el CLI (al mostrar la vista previa de aprobación).
    """
    title = (title or "").strip()
    content = (content or "").strip()
    if not title:
        raise ValueError("title が空です")
    if not content:
        raise ValueError("content が空です")
    if len(title) > MAX_TITLE_CHARS:
        raise ValueError(f"title は{MAX_TITLE_CHARS}文字以内にしてください（{len(title)}文字）")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(f"content は{MAX_CONTENT_CHARS}文字以内にしてください（{len(content)}文字）")
    if isinstance(lecture, bool) or not isinstance(lecture, int) or not 0 <= lecture <= MAX_LECTURE:
        raise ValueError(f"lecture は0〜{MAX_LECTURE}の整数にしてください（{lecture!r}）")

    # Clave de idempotencia: mismo contenido → mismo id → no se guarda dos veces (Clase 3, Partes 4 y 7)
    entry_id = hashlib.sha256(f"{lecture}\n{title}\n{content}".encode("utf-8")).hexdigest()[:12]
    now = now or datetime.now().astimezone()
    base = LEARNING_LOG_DIR.resolve()
    path = (base / f"{now:%Y-%m-%d}_{_slugify(title)}_{entry_id}.md").resolve()
    if path.parent != base:  # defensa en profundidad: nunca fuera de learning_log/
        raise ValueError("保存先が learning_log/ の外になります")

    markdown = (
        "---\n"
        f"id: {entry_id}\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"lecture: {lecture}\n"
        f"created_at: {now.isoformat(timespec='seconds')}\n"
        "saved_by: save_learning_log (利用者の承認あり)\n"
        "---\n\n"
        f"# {title}\n\n{content}\n"
    )
    return LearningLogEntry(entry_id, title, content, lecture, path, markdown)


def find_existing_log(entry_id: str) -> Path | None:
    """Busca si ya existe un registro con el mismo id (en cualquier fecha)."""
    if not LEARNING_LOG_DIR.exists():
        return None
    return next(iter(sorted(LEARNING_LOG_DIR.glob(f"*_{entry_id}.md"))), None)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def save_learning_log(title: str, content: str, lecture: int) -> str:
    """学習の記録（学んだこと・気づき・疑問など）を learning_log/ フォルダに Markdown ファイルとして保存する。

    利用者が「記録して」「保存して」「学習ログに残して」のように、保存をはっきり頼んだときだけ使う。
    保存は取り消しにくい操作なので、実行前に利用者の承認を求める。承認されなければ保存されない。
    title: 記録の見出し（80文字以内）。
    content: 記録の本文（2000文字以内）。利用者が話した内容をもとにまとめ、推測で事実を足さない。
    lecture: 関係する回（1〜13の整数）。特定の回がなければ 0。
    """
    try:
        entry = prepare_learning_log(title, content, lecture)
    except ValueError as e:
        # No se lanza la excepción: se devuelve el motivo para que el modelo lo corrija o lo informe
        return json.dumps({"saved": False, "reason": str(e)}, ensure_ascii=False)

    existing = find_existing_log(entry.entry_id)
    if existing:
        # Reintento tras un corte, o la misma petición dos veces: devolver el resultado registrado
        return json.dumps(
            {"saved": False, "already_exists": True, "path": _display_path(existing)}, ensure_ascii=False
        )

    entry.path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Modo "x": creación exclusiva. Si otro proceso lo creó entre medias, no se sobrescribe
        with open(entry.path, "x", encoding="utf-8") as f:
            f.write(entry.markdown)
    except FileExistsError:
        return json.dumps(
            {"saved": False, "already_exists": True, "path": _display_path(entry.path)}, ensure_ascii=False
        )
    return json.dumps(
        {"saved": True, "path": _display_path(entry.path), "id": entry.entry_id}, ensure_ascii=False
    )
