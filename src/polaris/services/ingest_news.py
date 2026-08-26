"""RSS/Atomフィードからニュース記事を取り込むIngestパイプライン(008-daily-digest-domain Phase A).

`services/ingest_paper.py`と同じ「repoとagentを受け取って組み立てる」パターン。
CLI(`cli/ingest_news.py`)から1日1回呼ばれる想定で、チャットのターン内実行ではないため
`services/progress.py`(進捗表示)は使わない。

トピック分類は行わない: source_labelはフィード単位で静的に決まる(spec の対立軸の
定義方針)ため、記事単位の追加LLM分類は不要と判断した。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

from polaris.adapters.rss.client import RssFetchError, fetch_feed
from polaris.domain.entities import Item, ItemType, NewsRecord

if TYPE_CHECKING:
    import httpx

    from polaris.agent.structure_news import NewsStructurer
    from polaris.db.news_repository import NewsRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

__all__ = ["IngestNewsResult", "ingest_all_feeds"]


class IngestNewsResult(NamedTuple):
    """`ingest_all_feeds` の戻り値."""

    fetched: int
    created: int
    skipped: int
    failed: int


async def _ingest_feed(
    feed_name: str,
    feed_url: str,
    feed_label: str,
    *,
    repo: NewsRepository,
    structurer: NewsStructurer,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> tuple[int, int, int]:
    """1フィード分を処理する。戻り値は (fetched, created, skipped)."""
    entries = await fetch_feed(
        feed_url,
        client=http_client,
        timeout_seconds=settings.news.timeout_seconds,
        max_entries=settings.news.max_entries_per_feed,
    )

    created = 0
    skipped = 0
    for entry in entries:
        if repo.find_by_source_url(entry.url) is not None:
            skipped += 1
            continue

        structured = await structurer.structure(title=entry.title, summary=entry.summary)
        now = datetime.now(UTC)
        record = NewsRecord(
            id=uuid.uuid4().hex,
            item_id="",  # 直後に確定させる
            source_name=feed_name,
            source_label=feed_label,
            published_at=entry.published_at or now,
            source_url=entry.url,
        )
        item = Item(
            id=uuid.uuid4().hex,
            item_type=ItemType.news_article,
            title=entry.title,
            summary=structured.summary,
            created_at=now,
            source_ref=f"news:{record.id}",
        )
        record.item_id = item.id
        repo.save_news(item, record)
        created += 1

    return len(entries), created, skipped


async def ingest_all_feeds(
    *,
    repo: NewsRepository,
    structurer: NewsStructurer,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> IngestNewsResult:
    """`settings.news.feeds` を順に処理する.

    1フィードのHTTP取得失敗が他フィードの処理を止めないよう、フィード単位で
    try/exceptする(`services/ingest_paper.py`のPDF取得失敗時のフォールバック方針と
    同じ考え方)。
    """
    fetched = created = skipped = failed = 0

    for feed in settings.news.feeds:
        try:
            feed_fetched, feed_created, feed_skipped = await _ingest_feed(
                feed.name,
                feed.url,
                feed.label,
                repo=repo,
                structurer=structurer,
                http_client=http_client,
                settings=settings,
            )
        except RssFetchError:
            logger.exception("フィードの取り込みに失敗しました: name=%s, url=%s", feed.name, feed.url)
            failed += 1
            continue

        fetched += feed_fetched
        created += feed_created
        skipped += feed_skipped
        logger.info(
            "フィード取り込み完了: name=%s, fetched=%d, created=%d, skipped=%d",
            feed.name,
            feed_fetched,
            feed_created,
            feed_skipped,
        )

    return IngestNewsResult(fetched=fetched, created=created, skipped=skipped, failed=failed)
