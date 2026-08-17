"""論文チャットエージェント.

ツールは2つのみ: arXiv URL の取り込み(save_paper)と一覧取得(list_papers)。
確認を挟まず、URL が来たら即座に保存する(受け入れ条件「URLを貼ってから一覧に
反映されるまで一往復で完結する」を満たすため)。save_paper は 002-papers-ingest-full
以降、PDF取得・本文抽出・チャンク分割・Embedding生成までのフルパイプラインを実行する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent

from polaris.services.ingest_paper import InvalidPaperUrlError, ingest_paper_from_url

from .model import build_model

if TYPE_CHECKING:
    from polaris.adapters.embeddings import EmbeddingModel
    from polaris.agent.structure_paper import PaperStructurer
    from polaris.db.repository import PaperRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

_INSTRUCTIONS = """\
あなたは個人用の論文管理アシスタントです。次のルールに従ってください。

- ユーザーのメッセージに arXiv の URL(または arXiv ID)が含まれていたら、
  必ず save_paper ツールを呼び出して保存してください。確認は不要です。
- 「保存した論文」「今までの論文一覧」のように尋ねられたら list_papers ツールを呼び出してください。
- 回答はツールの結果だけを根拠にし、推測で情報を補わないでください。
- 日本語で簡潔に答えてください。
"""


class PaperSummary(BaseModel):
    """一覧表示用の論文サマリ."""

    title: str
    authors: list[str]
    year: int | None
    arxiv_id: str | None


def build_chat_agent(
    settings: Settings,
    repo: PaperRepository,
    *,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
) -> Agent:
    """設定とリポジトリ・Embedding/Structure依存から論文チャットエージェントを組み立てる."""
    model = build_model(settings)
    agent = Agent(model, instructions=_INSTRUCTIONS)
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def save_paper(url: str) -> str:
        """ArXiv の URL からメタデータ・本文を取得し、チャンク分割・Embedding生成まで行って保存する.

        Args:
            url: arXiv の論文 URL(例: https://arxiv.org/abs/2401.12345)。

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
                settings=settings,
            )
        except InvalidPaperUrlError:
            return f"'{url}' から arXiv の論文IDを特定できませんでした。"

        authors = "、".join(result.record.authors) if result.record.authors else "不明"
        status = "新規に保存しました" if result.created else "既に保存済みでした"
        return (
            f"{status}: 『{result.item.title}』(著者: {authors}, arXiv:{result.record.arxiv_id}, "
            f"チャンク数: {len(result.chunks)})"
        )

    @agent.tool_plain
    def list_papers() -> list[PaperSummary]:
        """保存済みの論文一覧を返す."""
        logger.info("tool call: list_papers()")
        return [
            PaperSummary(title=item.title, authors=record.authors, year=record.year, arxiv_id=record.arxiv_id)
            for item, record in repo.list_papers()
        ]

    return agent
