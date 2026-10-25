"""第1回: 素のLLMに質問するスクリプト。

使い方:
    uv run python -m app.ask "LoRAとは何ですか？"
    uv run python -m app.ask            # 質問を省略すると、講座に固有の質問をする
    uv run python -m app.ask "LoRAとは？" --temperature 0
    uv run python -m app.ask --chat     # 実装課題: 会話履歴を保ったまま続けて質問する

ツールを持たない「素の」呼び出し。
講座に固有のことを聞くと、「分からない」と答えるか、一般論でもっともらしく答える
（講座の実際とは違う）ことを確かめよう。
（第3回で、用語集を検索できるエージェントにして改善する）
"""

import argparse

from google import genai
from google.genai import errors, types

from app.config import MODEL, api_error_message, get_api_key

# 講座に固有の質問。正しい答えは data/glossary.json の homework-levels にある
DEFAULT_QUESTION = "AIE2026の講座の宿題にある「3レベル」とは何ですか？"

# 会話モードを終了する入力
EXIT_WORDS = {"", "exit", "quit", "salir", "終了"}


def build_config(temperature: float | None) -> types.GenerateContentConfig | None:
    """temperature が指定されたときだけ config を作る（None ならモデルの既定値）。"""
    if temperature is None:
        return None
    return types.GenerateContentConfig(temperature=temperature)


def format_usage(usage: types.GenerateContentResponseUsageMetadata | None) -> str:
    """usage_metadata を1行の文字列にする。

    thinking 対応モデルでは、回答本文（出力）とは別に「思考トークン」が数えられる。
    画面には出ないが、課金・レート制限（トークン/分）の対象になるので分けて表示する。
    """
    if usage is None:
        return "[tokens] 取得できませんでした"
    prompt = usage.prompt_token_count or 0
    output = usage.candidates_token_count or 0
    thoughts = usage.thoughts_token_count or 0
    total = usage.total_token_count or (prompt + output + thoughts)
    return f"[tokens] 入力 {prompt} / 出力 {output} / 思考 {thoughts} / 合計 {total}"


def ask(question: str, temperature: float | None = None) -> str:
    client = genai.Client(api_key=get_api_key())
    response = client.models.generate_content(
        model=MODEL, contents=question, config=build_config(temperature)
    )

    # 第1回 演習: 入力トークン数と出力トークン数を表示する
    print(format_usage(response.usage_metadata))

    return response.text


def chat(temperature: float | None = None) -> None:
    """実装課題: 会話履歴を保ったまま続けて質問する。

    client.chats は送受信したメッセージを内部の履歴に積み、
    毎回「これまでの履歴 + 新しい質問」をモデルに送る。
    そのため入力トークン数はターンごとに増えていく（表示で確認できる）。
    """
    client = genai.Client(api_key=get_api_key())
    session = client.chats.create(model=MODEL, config=build_config(temperature))
    print("会話モード。空行 / exit / salir で終了。\n")

    while True:
        try:
            question = input("あなた> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question.lower() in EXIT_WORDS:
            break
        try:
            response = session.send_message(question)
        except errors.APIError as e:
            # 1回失敗しても会話は続けられる（失敗したターンは履歴に残らない）
            print(api_error_message(e.code, e.message))
            continue
        print(f"\nモデル> {response.text}")
        print(format_usage(response.usage_metadata))
        print(f"[履歴] {len(session.get_history())} メッセージ\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="素のLLMに質問する")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--temperature", type=float, default=None,
        help="0〜2。省略するとモデルの既定値",
    )
    parser.add_argument(
        "--chat", action="store_true", help="会話履歴を保ったまま続けて質問する",
    )
    args = parser.parse_args()

    print(f"[model] {MODEL}")
    if args.temperature is not None:
        print(f"[temperature] {args.temperature}")

    if args.chat:
        chat(args.temperature)
        return

    print(f"[質問] {args.question}\n")
    try:
        print(ask(args.question, args.temperature))
    except errors.APIError as e:
        print(api_error_message(e.code, e.message))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
