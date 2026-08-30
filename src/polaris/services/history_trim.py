"""会話履歴中の古い全文取得ツール結果をプレースホルダに置換する(ADR-0012).

`get_paper_full_text` のような「対象を切り替えながら全文を会話に取り込む」toolは、
一度呼ばれるとその`ToolReturnPart`(数万トークン規模)が以後の全ターンで無条件に
再送され続ける。同じセッション内で複数論文を読む、同じ論文に再突入するといった
ケースでトークン量が単調に増え続けるため、ターン完了時に履歴内で一番新しい
`ToolReturnPart`だけを残し、それより古いものを短いプレースホルダに置き換える。

判定はitem_id等のドメイン知識を使わず、`tool_name`とメッセージ列内での出現順序
だけで行う(ADR-0012「検討した代替案」参照: `active_paper`との照合はDB再検索や
隠しマーカー埋め込みが必要になり不要な複雑さを生む)。`FULL_TEXT_TOOL_NAMES`に
tool名を追加するだけで、将来の`013-ir-analysis-domain`の`get_ir_full_text`等にも
同じ仕組みをそのまま適用できる。
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

# トリミング対象のtool名。ここに追加するだけで新しいtoolにも同じ「最新1件だけ残す」
# ルールが適用される(トリミングロジック自体の変更は不要)。get_diary_range(019-diary-domain
# User Story 5)も対象を切り替えながら全文相当のコンテキストを取り込むtoolのため追加した
# (research.md Decision 8)。
FULL_TEXT_TOOL_NAMES: frozenset[str] = frozenset({"get_paper_full_text", "get_diary_range"})


def trim_stale_full_text_results(messages: list[ModelMessage]) -> list[ModelMessage]:
    """`FULL_TEXT_TOOL_NAMES`に含まれるtoolについて、最新のToolReturnPart以外をプレースホルダに置換した新しいリストを返す.

    元の`messages`・その中の`ModelMessage`/`ToolReturnPart`は一切変更しない(呼び出し側が
    保持する`AgentRunResult.all_messages()`の戻り値をそのまま渡せる)。置換対象が無い
    メッセージはそのまま同じオブジェクトを新しいリストに含める。
    """
    call_queries = _index_tool_call_queries(messages)
    newest_call_id_by_tool = _index_newest_return_call_ids(messages)

    trimmed: list[ModelMessage] = []
    for message in messages:
        if not isinstance(message, ModelRequest) or not any(
            isinstance(part, ToolReturnPart) and _is_stale_return(part, newest_call_id_by_tool)
            for part in message.parts
        ):
            trimmed.append(message)
            continue

        new_parts = [
            _as_placeholder(part, call_queries)
            if isinstance(part, ToolReturnPart) and _is_stale_return(part, newest_call_id_by_tool)
            else part
            for part in message.parts
        ]
        trimmed.append(replace(message, parts=new_parts))

    return trimmed


def _is_stale_return(part: ToolReturnPart, newest_call_id_by_tool: dict[str, str]) -> bool:
    return part.tool_name in FULL_TEXT_TOOL_NAMES and part.tool_call_id != newest_call_id_by_tool.get(part.tool_name)


def _index_tool_call_queries(messages: list[ModelMessage]) -> dict[str, str]:
    """tool_call_id ⇒ 呼び出し時にモデルが渡した引数(プレースホルダの`query`用).

    引数名(`paper`/将来の`get_ir_full_text`の引数名など)はtoolごとに違いうるため、
    キー名は見ずに最初の値だけを使う。
    """
    queries: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_name in FULL_TEXT_TOOL_NAMES:
                queries[part.tool_call_id] = _first_arg_value(part.args_as_dict())
    return queries


def _first_arg_value(args: dict[str, Any]) -> str:
    return str(next(iter(args.values()))) if args else ""


def _index_newest_return_call_ids(messages: list[ModelMessage]) -> dict[str, str]:
    """tool_name ⇒ 履歴内で一番新しい(=最後に出現する)ToolReturnPartのtool_call_id."""
    newest: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_name in FULL_TEXT_TOOL_NAMES:
                newest[part.tool_name] = part.tool_call_id
    return newest


def _as_placeholder(part: ToolReturnPart, call_queries: dict[str, str]) -> ToolReturnPart:
    query = call_queries.get(part.tool_call_id, "")
    content = (
        f'<omitted tool="{part.tool_name}" query="{query}">'
        f"全文は省略されました。必要なら再度{part.tool_name}を呼び出してください。</omitted>"
    )
    return replace(part, content=content)
