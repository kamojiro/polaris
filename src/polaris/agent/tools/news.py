"""ニュース一覧ツール(list_news、ADR-0013で chat_agent.py から分割).

008-daily-digest-domain Phase A で追加した。ニュースの取り込み自体はチャットからは
できない(RSSの定期巡回、`cli/ingest_news.py`でのみ更新される)。
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 - NewsSummaryのフィールド型としてランタイムに解決される必要がある
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.agent.chat_state import ChatDeps
    from polaris.db.news_repository import NewsRepository

logger = logging.getLogger(__name__)

# source_labelごとの上限(全体への単一LIMITではない。NewsRepository.list_news参照)。
_RECENT_NEWS_LIMIT_PER_LABEL = 15

INSTRUCTIONS = """\
- 「ニュース一覧」「最近の記事」「今日のニュース」のように尋ねられたら list_news ツールを
  呼び出してください。list_news の結果は画面側で情報源のカテゴリごとに一覧表示されるため、
  あなたは結果を文章で列挙せず、「取り込み済みのニュース一覧を表示しました」程度の
  一言だけ返してください。ニュースの取り込み自体はチャットからはできません
  (RSSの定期巡回でのみ更新されます)。"""


class NewsSummary(BaseModel):
    """一覧表示用のニュース記事サマリ."""

    title: str
    source_name: str
    source_label: str
    summary: str
    published_at: datetime
    source_url: str


class NewsListResult(BaseModel):
    """list_news の戻り値."""

    news: list[NewsSummary]


def register(agent: Agent[ChatDeps, str], news_repo: NewsRepository) -> None:
    """list_news ツールを登録する(008-daily-digest-domain Phase A)."""

    @agent.tool_plain
    def list_news() -> NewsListResult:
        """取り込み済みのニュース記事一覧を返す(情報源のラベルごとに画面側でグルーピング表示される)."""
        logger.info("tool call: list_news()")
        news = [
            NewsSummary(
                title=item.title,
                source_name=record.source_name,
                source_label=record.source_label,
                summary=item.summary,
                published_at=record.published_at,
                source_url=record.source_url,
            )
            for item, record in news_repo.list_news(limit_per_label=_RECENT_NEWS_LIMIT_PER_LABEL)
        ]
        return NewsListResult(news=news)
