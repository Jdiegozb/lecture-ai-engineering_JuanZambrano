"""第3回: Pydantic AI で作る学習支援エージェント。

使い方:
    uv run python -m app.agent "AIE2026の講座で使う「lecNN-start タグ」とは何ですか？"
    uv run python -m app.agent --trace "LoRAとQLoRAの違いは？"   # ツール呼び出しを表示
    uv run python -m app.agent --mcp --trace "LoRAとは？"        # 第5回: ツールを MCP サーバーから受け取る
    uv run python -m app.agent --mcp --list-tools               # 第5回: モデルに見えるツール一覧（APIキー不要）
    uv run python -m app.agent --trace "今日学んだことを学習ログに保存して: ..."  # 宿題（実装）: 保存前に承認を求める

エージェント = モデル + ループ + ツール。
モデルは tools.py の関数を「ツール」として呼び出し、その結果を見て回答を作る。
第5回では、同じツールを MCP サーバー（app/mcp_server.py）経由で受け取る。
"""

import argparse
import inspect
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.exceptions import ModelHTTPError
from fastmcp import Client
from pydantic_ai.mcp import MCPToolset, StdioTransport
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.google import GoogleProvider

from app import tools
from app.config import MODEL, api_error_message, get_api_key

INSTRUCTIONS = """\
あなたはAIエンジニアリング講座（AIE2026）の学習支援エージェントです。
- 用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。
- 回の内容を聞かれたら get_lecture_summary を使う。
- 用語集に見つからないことは、推測で断定せず「用語集にはない」と伝える。
- 回答の最後に、関係する回（第N回）を示す。
- 宿題の答えそのものは書かず、考え方のヒントで導く。
- 確認問題を求められたら make_quiz を使う。
- 学習の記録の保存をはっきり頼まれたときだけ save_learning_log を使う。保存が承認されなかったとき（拒否・エラー）は、保存したと言わない。
"""

# モデルは実行時に渡す（テストではAPIを呼ばない TestModel に差し替えるため）
# output_type に DeferredToolRequests を加える: 承認待ちで止まったとき、その一覧が result.output になる
agent = Agent(instructions=INSTRUCTIONS, output_type=[str, DeferredToolRequests])
agent.tool_plain(tools.search_glossary)
agent.tool_plain(tools.get_lecture_summary)
agent.tool_plain(tools.make_quiz)  # 第3回 演習
# 宿題（実装）: 保存は取り消しにくいので、実行前に人の承認を挟む（human-in-the-loop）
agent.tool_plain(tools.save_learning_log, requires_approval=True)

# Límite de rondas de aprobación por pregunta. Lo cuenta el harness, no el modelo (Clase 3, Parte 7)
MAX_APPROVAL_ROUNDS = 3

# 第5回: 使う MCP サーバーの設定ファイル。Claude Desktop や Cursor と同じ "mcpServers" 形式
MCP_CONFIG = Path(__file__).resolve().parent / "mcp_servers.json"


def load_mcp_servers(config_path: Path = MCP_CONFIG) -> list[MCPToolset]:
    """設定ファイル（mcpServers 形式）を読み、サーバーごとに接続（MCPToolset）を作る。

    - "command" があれば stdio：サーバーをサブプロセスとして起動する
    - "url" があれば Streamable HTTP：起動済みのサーバーに接続する
    ツール名には「サーバー名_」を付ける（例: glossary_search_glossary）。複数のサーバーに
    同じ名前のツールがあっても区別できるようにするため。

    Pydantic AI には同じことをする load_mcp_toolsets() もある。ここで自分で組み立てているのは、
    古い SDK で作られたサーバー（fetch など）につなぐとき、接続方式の自動判定（"auto"）が
    警告を大量に出すため。"legacy" に固定すると新旧どちらのサーバーにも静かにつながる。
    """
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))["mcpServers"]
    toolsets = []
    for name, spec in config.items():
        if "url" in spec:
            transport = spec["url"]
        else:
            transport = StdioTransport(spec["command"], spec.get("args", []), env=spec.get("env"))
        toolsets.append(MCPToolset(Client(transport, mode="legacy")).prefixed(name))
    return toolsets


def build_mcp_agent(config_path: Path = MCP_CONFIG) -> Agent:
    """第5回: 関数を直接登録する代わりに、MCP サーバーが公開するツールを使うエージェント。INSTRUCTIONS は同じ。"""
    return Agent(instructions=INSTRUCTIONS, toolsets=load_mcp_servers(config_path))


def build_model() -> GoogleModel:
    return GoogleModel(MODEL, provider=GoogleProvider(api_key=get_api_key()))


def print_tools(target: Agent) -> None:
    """モデルに見えているツールの一覧（名前・説明文・引数）を表示する。LLM は呼ばない。

    TestModel（テストで使う偽モデル）にツール一覧を渡し、そこから読み出す。
    MCP サーバーのツールも、第3回の関数ツールも、モデルから見れば同じ形をしている。
    """
    model = TestModel(call_tools=[])
    target.run_sync("ツール一覧", model=model)
    tools_seen = model.last_model_request_parameters.function_tools
    print(f"モデルに見えているツール: {len(tools_seen)} 個")
    for tool in tools_seen:
        print(f"\n[{tool.name}]")
        print("  " + inspect.cleandoc(tool.description or "").replace("\n", "\n  "))
        params = tool.parameters_json_schema.get("properties", {})
        print(f"  引数: {json.dumps(params, ensure_ascii=False)}")


def print_trace(result, usage=None) -> None:
    """どのツールが、どの引数で呼ばれ、何を返したかを表示する。

    usage: 承認をはさんで run_sync を複数回呼んだときの合計（省略時は最後の実行分）。
    """
    print("\n--- trace ---")
    for message in result.all_messages():
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                print(f"[tool call]   {part.tool_name}({part.args})")
            elif isinstance(part, ToolReturnPart):
                print(f"[tool return] {part.tool_name} -> {str(part.content)[:120]}…")
    print(f"[usage] {usage if usage is not None else result.usage}")


# --- 宿題（実装）: 承認（human-in-the-loop）--------------------------------------

Decision = bool | ToolDenied  # True = aprobar; ToolDenied(mensaje) = rechazar y decir por qué al modelo
Approver = Callable[[ToolCallPart], Decision]


@dataclass
class RunOutcome:
    result: object  # AgentRunResult del último run_sync (all_messages() contiene toda la conversación)
    usage: object  # RunUsage sumado de todas las llamadas
    approval_rounds: int
    stopped_by_limit: bool


def describe_call(call: ToolCallPart) -> str:
    """Texto que ve la persona antes de aprobar: el archivo y el contenido EXACTOS que se escribirán."""
    args = call.args_as_dict()
    if call.tool_name == "save_learning_log":
        entry = tools.prepare_learning_log(**args)  # ValueError si los argumentos no son válidos
        return (
            f"保存先: {tools._display_path(entry.path)}\n"
            f"---- 保存される内容 ----\n{entry.markdown}------------------------"
        )
    return f"{call.tool_name}({json.dumps(args, ensure_ascii=False)})"


def cli_approver(call: ToolCallPart, input_fn: Callable[[str], str] = input, interactive: bool | None = None) -> Decision:
    """Pregunta en la terminal. Por defecto NO (solo 'y' / 'yes' / 'はい' aprueban)."""
    print(f"\n[承認待ち] ツール {call.tool_name} を実行しようとしています。")
    try:
        print(describe_call(call))
    except (TypeError, ValueError) as e:
        # Argumentos inválidos: no tiene sentido pedir aprobación; se rechaza y el modelo recibe el motivo
        print(f"[承認待ち] 引数が不正なので自動で拒否します: {e}")
        return ToolDenied(f"引数が不正なため実行していません: {e}")
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        # Sin persona delante (CI, tubería): nunca aprobar en silencio
        print("[承認待ち] 対話できない環境なので自動で拒否します。")
        return ToolDenied("対話できない環境のため、利用者の承認が得られず実行していません。")
    try:
        answer = input_fn("実行してよいですか？ [y/N]: ").strip().casefold()
    except (EOFError, KeyboardInterrupt):  # Ctrl-D / Ctrl-C = no (fallar hacia lo seguro)
        print()
        answer = ""
    if answer in {"y", "yes", "はい"}:
        return True
    return ToolDenied("利用者が実行を拒否しました。保存などの操作は行われていません。")


def run_with_approval(target: Agent, question: str, model, approver: Approver = cli_approver,
                      max_rounds: int = MAX_APPROVAL_ROUNDS) -> RunOutcome:
    """Bucle del harness: ejecutar → si hay herramientas pendientes de aprobación, preguntar →
    reanudar con el historial + las decisiones. Termina cuando la salida es texto o se alcanza el límite."""
    result = target.run_sync(question, model=model)
    usage = result.usage
    rounds = 0
    while isinstance(result.output, DeferredToolRequests):
        if rounds >= max_rounds:
            return RunOutcome(result, usage, rounds, stopped_by_limit=True)
        if result.output.calls:
            # Herramientas externas (no se usan en este curso): no sabemos ejecutarlas aquí
            raise RuntimeError(f"未対応の外部ツール呼び出し: {[c.tool_name for c in result.output.calls]}")
        rounds += 1
        decisions = DeferredToolResults(
            approvals={call.tool_call_id: approver(call) for call in result.output.approvals}
        )
        result = target.run_sync(
            message_history=result.all_messages(), deferred_tool_results=decisions, model=model
        )
        usage = usage + result.usage  # cada run_sync cuenta solo sus propias llamadas
    return RunOutcome(result, usage, rounds, stopped_by_limit=False)


def snapshot_logs() -> set[Path]:
    return set(tools.LEARNING_LOG_DIR.glob("*.md")) if tools.LEARNING_LOG_DIR.exists() else set()


def main() -> None:
    parser = argparse.ArgumentParser(description="学習支援エージェントに質問する")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--trace", action="store_true", help="ツール呼び出しを表示する")
    parser.add_argument("--mcp", action="store_true", help="第5回: ツールを MCP サーバー（app/mcp_servers.json）から受け取る")
    parser.add_argument("--list-tools", action="store_true", help="モデルに見えるツール一覧を表示して終了する（APIキー不要）")
    args = parser.parse_args()

    target = build_mcp_agent() if args.mcp else agent
    if args.list_tools:
        print_tools(target)
        return
    if not args.question:
        parser.error("質問を指定してください")

    print(f"[model] {MODEL}")
    if args.mcp:
        print("[tools] MCP サーバー（app/mcp_servers.json）")
    before = snapshot_logs()
    try:
        outcome = run_with_approval(target, args.question, build_model())
    except ModelHTTPError as e:
        print(api_error_message(e.status_code, str(e.body)[:200]))
        raise SystemExit(1)
    if outcome.stopped_by_limit:
        print(f"[停止] 承認待ちが {MAX_APPROVAL_ROUNDS} 回を超えたので止めました（未実行のツールがあります）。")
    else:
        print(outcome.result.output)

    # Comprobar el resultado por el ESTADO (archivos), no por lo que dice el modelo (Clase 3, Parte 7)
    created = sorted(snapshot_logs() - before)
    if created:
        print("\n[verify] 新しく保存されたファイル: " + ", ".join(tools._display_path(p) for p in created))
    elif outcome.approval_rounds:
        print("\n[verify] learning_log/ に新しいファイルはありません")
    if args.trace:
        print(f"[approval rounds] {outcome.approval_rounds}")
        print_trace(outcome.result, outcome.usage)


if __name__ == "__main__":
    main()
