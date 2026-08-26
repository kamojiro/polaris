"""RSS巡回バッチ(008-daily-digest-domain Phase A)のCLIエントリポイント.

`uv run python -m polaris.cli.ingest_news` で実行する。OS cronから1日1回叩く想定
(例: crontabに `0 7 * * * cd /path/to/polaris && uv run python -m polaris.cli.ingest_news`)。

FastAPIサーバーの生存に依存させないため、`api/app.py`とは別にEngine・Repository・
Structurerを自前で組み立てる(サーバー未起動時でも実行できる)。
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from polaris.agent.structure_news import AgentNewsStructurer, build_structure_news_agent
from polaris.db.news_repository import NewsRepository
from polaris.db.session import create_db_engine
from polaris.services.ingest_news import ingest_all_feeds
from polaris.settings import Settings

logger = logging.getLogger(__name__)


async def _run(settings: Settings) -> None:
    engine = create_db_engine(settings.DB_PATH, embedding_dim=settings.ingest.embedding_dim)
    repo = NewsRepository(engine)
    structurer = AgentNewsStructurer(build_structure_news_agent(settings))

    async with httpx.AsyncClient() as http_client:
        result = await ingest_all_feeds(repo=repo, structurer=structurer, http_client=http_client, settings=settings)

    logger.info(
        "Ingest完了: fetched=%d, created=%d, skipped=%d, failed=%d",
        result.fetched,
        result.created,
        result.skipped,
        result.failed,
    )


def main() -> None:
    """`python -m polaris.cli.ingest_news` のエントリポイント."""
    settings = Settings()
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
