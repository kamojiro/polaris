"""関連論文調査の受付ツール(research_related_papers、027-related-paper-research ユーザーストーリー1).

チャット側では`PaperResearchRecord(status="pending")`を1件作るだけに留め、実処理
(発見→粗い判定→精読→統合)は行わない(`add_todo`と同じ軽さ)。実行はcron駆動の
CLI(`cli/run_paper_research.py`)が担い、完了はフロントのバナーで通知される
(`023-daily-summary-notification`と同じUIパターン)。検索→複数論文取得→抽出→統合は
数分〜数十分かかりうるため、他のtool(数秒で完了する前提)と同じ同期チャットターン
には収めない(`specs/IDEAS.md`の判断)。

論文の指定方法は`get_paper_full_text`(`paper_qa.py`)と同様2通り: 論文モード中
(`ctx.deps.state.active_paper`)ならpaper引数を省略でき、モード外なら明示的に
arXiv ID/URLまたはタイトルを渡す。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

# RunContext/ChatDeps は research_related_papers の引数注釈として使われ、
# pydantic-ai が実行時にシグネチャから解決するため、`paper_qa.py`と同じ理由で
# TYPE_CHECKING に入れず実行時importにする(ruff の TC002 は意図的に無視する)。
from pydantic_ai import RunContext  # noqa: TC002

from polaris.adapters.arxiv.parser import extract_arxiv_id
from polaris.agent.chat_state import ChatDeps  # noqa: TC001
from polaris.domain.entities import PaperResearchRecord

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.db.paper_research_repository import PaperResearchRepository
    from polaris.db.repository import PaperRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
- 「この論文に関連する論文を集めて」「引用してる論文も含めて調べて」のように
  頼まれたら research_related_papers ツールを呼んでください。論文モード中
  (get_paper_full_text済み)なら paper 引数は省略してよく、その場合は今読んでいる
  論文が起点になります。論文モード外から頼まれた場合は、arXivのURL/ID、または
  保存済みのタイトルの一部を paper 引数に渡してください。
- この調査はバックグラウンドで実行され、数分〜数十分かかります。ツールを呼んだ
  直後にその場で調査結果が出るわけではないこと、完了するとチャット画面の通知
  バナーで知らされることをユーザーに伝えてください。"""


def register(
    agent: Agent[ChatDeps, str],
    research_repo: PaperResearchRepository,
    *,
    paper_repo: PaperRepository,
    settings: Settings,
) -> None:
    """research_related_papers ツールを登録する(027-related-paper-research)."""

    @agent.tool
    async def research_related_papers(ctx: RunContext[ChatDeps], paper: str | None = None) -> str:
        """論文を起点に引用チェイニングで関連論文を集める調査を、キューに1件追加する.

        Args:
            ctx: pydantic-ai が注入する実行コンテキスト(論文モードのstateを読む)。
            paper: 起点論文を指す文字列(arXivのURL/ID、または保存時のタイトルの一部)。
                省略した場合、現在の論文モードで読んでいる論文が起点になる。

        Returns:
            受付結果を表す短い日本語メッセージ(機能無効・論文特定失敗・受付済みのいずれか)。

        """
        logger.info("tool call: research_related_papers(paper=%s)", paper)
        if not settings.semantic_scholar.api_key:
            return "関連論文調査機能は現在無効です(Semantic ScholarのAPIキーが未設定)。"

        if paper is None:
            active = ctx.deps.state.active_paper
            if active is None:
                return (
                    "起点となる論文が特定できませんでした。論文モードに入るか、"
                    "arXivのURL/ID・保存済みのタイトルを指定してください。"
                )
            item_id, title = active.item_id, active.title
        else:
            query = extract_arxiv_id(paper) or paper
            matches = paper_repo.search_papers(query)
            if not matches:
                return (
                    f"'{paper}' に該当する論文が見つかりませんでした。list_papers で保存済みの論文を確認してください。"
                )
            if len(matches) > 1:
                titles = "、".join(f"『{item.title}』" for item, _record in matches)
                return (
                    f"複数の論文が該当しました: {titles}。どの論文か、タイトルをもう少し詳しく指定してください。"
                )
            item, _record = matches[0]
            item_id, title = item.id, item.title

        existing = research_repo.find_active_by_seed(item_id)
        if existing is not None:
            return (
                f"『{title}』についての調査は既に受付済みです(状態: {existing.status})。"
                "完了するとバナーで通知されます。"
            )

        record = PaperResearchRecord(
            id=uuid.uuid4().hex,
            seed_item_id=item_id,
            seed_title=title,
            status="pending",
            created_at=datetime.now(UTC),
        )
        research_repo.save(record)
        return (
            f"『{title}』に関連する論文の調査をキューに追加しました。"
            "完了までしばらく(数分〜数十分)かかります。完了するとバナーで通知されます。"
        )
