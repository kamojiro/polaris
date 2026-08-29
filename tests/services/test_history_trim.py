"""trim_stale_full_text_results(ADR-0012)の純ロジックテスト.

実LLM・DBは使わず、pydantic-aiのメッセージ型を直接組み立てて検証する。
"""

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from polaris.services.history_trim import trim_stale_full_text_results

_FULL_TEXT_A = "# Attention Is All You Need\n" + "本文" * 10_000
_FULL_TEXT_B = "# BERT\n" + "本文" * 10_000


def _sample_messages() -> list[ModelMessage]:
    """2つの論文(A→B)を順に読み、その間にlist_papersも呼ぶ、という会話履歴を組み立てる."""
    return [
        ModelRequest(parts=[UserPromptPart(content="attention is all you needの内容を教えて")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="get_paper_full_text",
                    tool_call_id="call-1",
                    args={"paper": "attention is all you need"},
                )
            ]
        ),
        ModelRequest(
            parts=[ToolReturnPart(tool_name="get_paper_full_text", tool_call_id="call-1", content=_FULL_TEXT_A)]
        ),
        ModelResponse(parts=[TextPart(content="Attentionは...")]),
        ModelRequest(parts=[UserPromptPart(content="保存済みの論文一覧は?")]),
        ModelResponse(parts=[ToolCallPart(tool_name="list_papers", tool_call_id="call-2", args={})]),
        ModelRequest(parts=[ToolReturnPart(tool_name="list_papers", tool_call_id="call-2", content="papers: [...]")]),
        ModelResponse(parts=[TextPart(content="一覧を表示しました")]),
        ModelRequest(parts=[UserPromptPart(content="次はBERTについて教えて")]),
        ModelResponse(
            parts=[ToolCallPart(tool_name="get_paper_full_text", tool_call_id="call-3", args={"paper": "bert"})]
        ),
        ModelRequest(
            parts=[ToolReturnPart(tool_name="get_paper_full_text", tool_call_id="call-3", content=_FULL_TEXT_B)]
        ),
        ModelResponse(parts=[TextPart(content="BERTは...")]),
    ]


def _tool_return(messages: list[ModelMessage], tool_call_id: str) -> ToolReturnPart:
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_call_id == tool_call_id:
                return part
    msg = f"tool_call_id={tool_call_id} のToolReturnPartが見つかりません"
    raise AssertionError(msg)


def test_trim_replaces_only_older_full_text_returns() -> None:
    """古い(A)get_paper_full_text結果だけがプレースホルダになり、最新(B)は無傷."""
    original = _sample_messages()

    trimmed = trim_stale_full_text_results(original)

    old_return = _tool_return(trimmed, "call-1")
    assert old_return.content == (
        '<omitted tool="get_paper_full_text" query="attention is all you need">'
        "全文は省略されました。必要なら再度get_paper_full_textを呼び出してください。</omitted>"
    )

    newest_return = _tool_return(trimmed, "call-3")
    assert newest_return.content == _FULL_TEXT_B


def test_trim_leaves_unrelated_tool_results_untouched() -> None:
    """get_paper_full_text以外のtool(list_papers)の結果は一切変更されない."""
    trimmed = trim_stale_full_text_results(_sample_messages())

    list_papers_return = _tool_return(trimmed, "call-2")
    assert list_papers_return.content == "papers: [...]"


def test_trim_does_not_mutate_the_original_messages() -> None:
    """元のmessagesリスト・その中のオブジェクトは一切変更されない(呼び出し元が使い回せる)."""
    original = _sample_messages()
    original_old_content = _tool_return(original, "call-1").content

    trim_stale_full_text_results(original)

    assert _tool_return(original, "call-1").content == original_old_content == _FULL_TEXT_A


def test_trim_preserves_message_count_and_order() -> None:
    """メッセージの件数・順序自体は変えない(内容の一部を置換するだけ)."""
    original = _sample_messages()

    trimmed = trim_stale_full_text_results(original)

    assert len(trimmed) == len(original)
    assert [type(m) for m in trimmed] == [type(m) for m in original]


def test_trim_is_noop_when_no_full_text_tool_was_called() -> None:
    """全文取得toolが一度も呼ばれていない履歴はそのまま返る."""
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="TODO一覧を見せて")]),
        ModelResponse(parts=[ToolCallPart(tool_name="list_todos", tool_call_id="call-1", args={})]),
        ModelRequest(parts=[ToolReturnPart(tool_name="list_todos", tool_call_id="call-1", content="todos: [...]")]),
        ModelResponse(parts=[TextPart(content="一覧を表示しました")]),
    ]

    trimmed = trim_stale_full_text_results(messages)

    assert trimmed == messages
