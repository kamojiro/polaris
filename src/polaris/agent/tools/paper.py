"""論文Ingestツール(save_paper/list_papers、ADR-0013で chat_agent.py から分割).

論文ツール(save_paper/list_papers)は 002-papers-ingest-full 以降、PDF取得・
本文抽出・チャンク分割までのフルパイプラインを実行する(Embedding生成はADR-0011
により行わない)。014-paper-url-pdf-ingest で arXiv 以外(PDF直リンクURL、
`upload://<id>` 経由のローカルPDF)にも対応した。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel

from polaris.services.ingest_paper import ingest_paper_from_url
from polaris.services.paper_source import InvalidPaperUrlError

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.agent.chat_state import ChatDeps
    from polaris.agent.extract_metadata import PaperMetadataExtractor
    from polaris.agent.structure_paper import PaperStructurer
    from polaris.db.repository import PaperRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

# 一覧表示の上限。件数が増えるほど DB 負荷・LLM に渡すトークン量が際限なく
# 増えないよう、フロントではなくここ(list_papers の SQL LIMIT)で絞る。
_RECENT_PAPERS_LIMIT = 20

INSTRUCTIONS = """\
- ユーザーのメッセージに arXiv の URL/ID、PDFへの直リンクURL、または
  `upload://` から始まる文字列が含まれていたら、必ず save_paper ツールを
  呼び出して保存してください。確認は不要です。
  save_paper の結果に含まれる要約は省略せずそのままユーザーに伝えてください。
- 「保存した論文」「今までの論文一覧」のように尋ねられたら list_papers ツールを呼び出してください。
  list_papers の結果は画面側で一覧表示されるため、あなたは結果を文章で列挙せず、
  「保存済みの論文一覧を表示しました」程度の一言だけ返してください。"""


class PaperSummary(BaseModel):
    """一覧表示用の論文サマリ."""

    title: str
    authors: list[str]
    year: int | None
    arxiv_id: str | None


class PaperListResult(BaseModel):
    """list_papers の戻り値.

    `papers` は直近 `_RECENT_PAPERS_LIMIT` 件のみ、`total_count` は保存済みの
    総件数(省略された残り件数をフロントが計算できるようにするため)。
    """

    papers: list[PaperSummary]
    total_count: int


def register(
    agent: Agent[ChatDeps, str],
    repo: PaperRepository,
    *,
    settings: Settings,
    structurer: PaperStructurer,
    extractor: PaperMetadataExtractor,
) -> None:
    """save_paper/list_papers ツールを登録する(002-papers-ingest-full/014-paper-url-pdf-ingest)."""
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def save_paper(url: str) -> str:
        """arXiv/PDF直リンクURL/アップロード済みPDFからメタデータ・本文を取得し、チャンク分割まで行って保存する.

        Args:
            url: arXiv の論文 URL/ID(例: https://arxiv.org/abs/2401.12345)、
                PDFへの直リンクURL、または `upload://<id>`(POST /api/papers/upload
                が発行した ID)。

        Returns:
            保存結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: save_paper(url=%s)", url)
        try:
            result = await ingest_paper_from_url(
                url,
                repo=repo,
                http_client=http_client,
                structurer=structurer,
                extractor=extractor,
                settings=settings,
            )
        except InvalidPaperUrlError:
            return (
                f"'{url}' から論文の取り込み元を特定できませんでした。"
                "arXivのURL/ID、またはPDFへの直リンクURLを貼ってください。"
            )

        status = "新規に保存しました" if result.created else "既に保存済みでした"
        source_label = f"arXiv:{result.record.arxiv_id}" if result.record.arxiv_id else result.record.source_url
        return (
            f"{status}: 『{result.item.title}』({source_label}, チャンク数: {len(result.chunks)})\n\n"
            f"要約: {result.item.summary}"
        )

    @agent.tool_plain
    def list_papers() -> PaperListResult:
        """保存済みの論文一覧を直近分だけ返す(総件数も併せて返す)."""
        logger.info("tool call: list_papers()")
        papers = [
            PaperSummary(title=item.title, authors=record.authors, year=record.year, arxiv_id=record.arxiv_id)
            for item, record in repo.list_papers(limit=_RECENT_PAPERS_LIMIT)
        ]
        return PaperListResult(papers=papers, total_count=repo.count_papers())
