"""論文チャットエージェント.

ツールは2つのみ: 論文の取り込み(save_paper)と一覧取得(list_papers)。
確認を挟まず、URL等が来たら即座に保存する(受け入れ条件「URLを貼ってから一覧に
反映されるまで一往復で完結する」を満たすため)。save_paper は 002-papers-ingest-full
以降、PDF取得・本文抽出・チャンク分割・Embedding生成までのフルパイプラインを実行する。
014-paper-url-pdf-ingest で arXiv 以外(PDF直リンクURL、`upload://<id>` 経由の
ローカルPDF)にも対応した。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent

from polaris.services.ingest_paper import ingest_paper_from_url
from polaris.services.paper_source import InvalidPaperUrlError

from .model import build_model

if TYPE_CHECKING:
    from polaris.adapters.embeddings import EmbeddingModel
    from polaris.agent.extract_metadata import PaperMetadataExtractor
    from polaris.agent.structure_paper import PaperStructurer
    from polaris.db.repository import PaperRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

# 一覧表示の上限。件数が増えるほど DB 負荷・LLM に渡すトークン量が際限なく
# 増えないよう、フロントではなくここ(list_papers の SQL LIMIT)で絞る。
_RECENT_PAPERS_LIMIT = 20

_INSTRUCTIONS = """\
あなたは個人用の論文管理アシスタントです。次のルールに従ってください。

- ユーザーのメッセージに arXiv の URL/ID、PDFへの直リンクURL、または
  `upload://` から始まる文字列が含まれていたら、必ず save_paper ツールを
  呼び出して保存してください。確認は不要です。
  save_paper の結果に含まれる要約は省略せずそのままユーザーに伝えてください。
- 「保存した論文」「今までの論文一覧」のように尋ねられたら list_papers ツールを呼び出してください。
  list_papers の結果は画面側で一覧表示されるため、あなたは結果を文章で列挙せず、
  「保存済みの論文一覧を表示しました」程度の一言だけ返してください。
- 回答はツールの結果だけを根拠にし、推測で情報を補わないでください。
- 日本語で簡潔に答えてください。
"""


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


def build_chat_agent(
    settings: Settings,
    repo: PaperRepository,
    *,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
    extractor: PaperMetadataExtractor,
) -> Agent:
    """設定とリポジトリ・Embedding/Structure/メタデータ抽出依存から論文チャットエージェントを組み立てる."""
    model = build_model(settings)
    agent = Agent(model, instructions=_INSTRUCTIONS)
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def save_paper(url: str) -> str:
        """arXiv/PDF直リンクURL/アップロード済みPDFからメタデータ・本文を取得し、チャンク分割・Embedding生成まで行って保存する.

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
                embedder=embedder,
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

    return agent
