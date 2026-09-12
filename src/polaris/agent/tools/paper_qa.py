"""論文QAツール(get_paper_full_text/exit_paper_mode、ADR-0013で chat_agent.py から分割).

015-paper-qa-chat で追加した。ベクトル検索(Chunk/Embedding)は経由せず、対象論文の
抽出済み全文をそのまま会話に取り込む方式。一度取り込んだ全文は会話履歴に残るため、
同じ論文について複数ターン質問しても ツールを再度呼ぶ必要はない。

「論文モード」は、get_paper_full_text が成功すると AG-UI の state
(ChatUIState.active_paper)に「今読んでいる論文」を記録し、動的instructions
(register 内で登録)がそれを見て「曖昧な質問もこの論文への質問として解釈してよい」
という指示を追加する。会話履歴だけに頼るのではなく、明示的な state を LLM への
指示とフロントのバッジ表示の両方に使う。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

# RunContext/ChatDeps は get_paper_full_text/exit_paper_mode/_paper_mode_instructions の
# 引数の型注釈として使われ、pydantic-ai が実行時にシグネチャから解決する
# (`from __future__ import annotations` で文字列注釈になるため、TYPE_CHECKING
# ブロックに入れると実行時に解決できず NameError になる)。そのため ruff の
# TC001/TC002 は意図的に無視する。
from pydantic_ai import RunContext  # noqa: TC002

from polaris.adapters.arxiv.parser import extract_arxiv_id
from polaris.agent.chat_state import ActivePaper, ChatDeps
from polaris.progress import set_progress
from polaris.services.paper_full_text import load_full_text

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.db.repository import PaperRepository
    from polaris.domain.entities import Item, PaperRecord
    from polaris.services.paper_full_text import PaperFullText
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
- 特定の論文の内容について質問されたら(「〇〇という論文の手法は?」等)、まず
  get_paper_full_text で全文を会話に取り込んでから答えてください。同じ論文に
  ついて続けて質問された場合、全文は既に会話履歴に残っているのでツールを
  再度呼ぶ必要はありません。複数の論文を比較する場合は、それぞれについて
  ツールを呼んでください。"""


def _format_full_text(item: Item, record: PaperRecord, full_text: PaperFullText) -> str:
    """get_paper_full_text の戻り値を組み立てる(ヘッダ+本文)."""
    arxiv_label = f", arXiv:{record.arxiv_id}" if record.arxiv_id else ""
    header = f"# 『{item.title}』({'、'.join(record.authors) or '著者不明'}{arxiv_label})"
    truncated_note = "\n(全文が長いため先頭部分のみ表示しています)" if full_text.truncated else ""
    return f"{header}{truncated_note}\n---\n{full_text.text}"


def register(agent: Agent[ChatDeps, str], repo: PaperRepository, *, settings: Settings) -> None:
    """get_paper_full_text/exit_paper_mode ツールと論文モードの動的instructionsを登録する(015-paper-qa-chat)."""

    @agent.tool
    async def get_paper_full_text(ctx: RunContext[ChatDeps], paper: str) -> str:
        """保存済み論文の本文全文を取得し、会話に取り込む(論文モードに入る).

        Args:
            ctx: pydantic-ai が注入する実行コンテキスト(論文モードのstateを保持)。
            paper: 対象論文を指す文字列(arXivのURL/ID、または保存時のタイトルの一部)。

        Returns:
            論文の本文全文(見つからない/複数該当する場合はその旨の日本語メッセージ)。

        """
        logger.info("tool call: get_paper_full_text(paper=%s)", paper)
        query = extract_arxiv_id(paper) or paper
        matches = repo.search_papers(query)
        if not matches:
            return f"'{paper}' に該当する論文が見つかりませんでした。list_papers で保存済みの論文を確認してください。"
        if len(matches) > 1:
            titles = "、".join(f"『{item.title}』" for item, _record in matches)
            return f"複数の論文が該当しました: {titles}。どの論文か、タイトルをもう少し詳しく指定してください。"

        item, record = matches[0]
        set_progress("stage", "論文の全文を読み込み中…")
        try:
            full_text = await load_full_text(item, record, repo=repo, max_chars=settings.chat.max_full_text_chars)
        finally:
            set_progress("stage", None)
        ctx.deps.state.active_paper = ActivePaper(item_id=item.id, title=item.title)
        return _format_full_text(item, record, full_text)

    @agent.tool
    def exit_paper_mode(ctx: RunContext[ChatDeps]) -> str:
        """論文モードを終了する(ユーザーが別の話題に移った、または明示的に終了を求めた場合に呼ぶ)."""
        logger.info("tool call: exit_paper_mode()")
        ctx.deps.state.active_paper = None
        return "論文モードを終了しました。"

    @agent.instructions
    def _paper_mode_instructions(ctx: RunContext[ChatDeps]) -> str | None:
        active = ctx.deps.state.active_paper
        if active is None:
            return None
        return (
            f"現在は論文『{active.title}』について読んでいる「論文モード」です。"
            "ユーザーの質問が曖昧でも、明確に他の話題に触れていなければこの論文についての"
            "質問だと解釈して回答してください(全文は会話履歴に既にあるので "
            "get_paper_full_text を再度呼ぶ必要はありません)。ユーザーが明確に別の話題へ"
            "移ったり、論文の話を終えたいと言ったりしたら exit_paper_mode を呼んでください。"
        )
