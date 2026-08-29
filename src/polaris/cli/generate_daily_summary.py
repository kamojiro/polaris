"""日次サマリー生成バッチ(023-daily-summary-notification)のCLIエントリポイント.

`uv run python -m polaris.cli.generate_daily_summary` で実行する。`cli/ingest_news.py`
と同じくOS cronから叩く想定(例: crontabに
`0 4 * * * cd /path/to/polaris && uv run python -m polaris.cli.generate_daily_summary`)。

深夜〜早朝のcronから叩く前提のため、既定では設定のタイムゾーン(`settings.daily_summary.timezone`、
既定JST)で「昨日」を対象にする(走った瞬間の「今日」はまだ始まったばかりのため)。
`--date YYYY-MM-DD`でデバッグ用に対象日を指定できる。

FastAPIサーバーの生存に依存させないため、`api/app.py`とは別にEngine・Repository・
Agentを自前で組み立てる。GPUは使わないため`QwenEmbedder`はロードしない。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from polaris.agent.daily_summary import AgentDailySummarizer, build_daily_summary_agent
from polaris.db.daily_summary_repository import DailySummaryRepository
from polaris.db.memory_repository import MemoryRepository
from polaris.db.news_repository import NewsRepository
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.db.todo_repository import TodoRepository
from polaris.services.daily_summary import generate_daily_summary
from polaris.settings import Settings

logger = logging.getLogger(__name__)


def _default_target_date(settings: Settings) -> date:
    """設定のタイムゾーンでの「昨日」を返す(深夜〜早朝cron前提の既定値)."""
    now_local = datetime.now(ZoneInfo(settings.daily_summary.timezone))
    return (now_local - timedelta(days=1)).date()


async def _run(settings: Settings, target_date: date) -> None:
    engine = create_db_engine(settings.DB_PATH, embedding_dim=settings.ingest.embedding_dim)
    summarizer = AgentDailySummarizer(build_daily_summary_agent(settings))

    result = await generate_daily_summary(
        day=target_date,
        summarizer=summarizer,
        paper_repo=PaperRepository(engine),
        todo_repo=TodoRepository(engine),
        memory_repo=MemoryRepository(engine),
        news_repo=NewsRepository(engine),
        summary_repo=DailySummaryRepository(engine),
        settings=settings,
    )
    if result is None:
        logger.info("日次サマリー: %sは活動が無かったため生成しませんでした", target_date)
    else:
        logger.info("日次サマリー生成完了: date=%s, content_chars=%d", target_date, len(result.content))


def main() -> None:
    """`python -m polaris.cli.generate_daily_summary` のエントリポイント."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="対象日(YYYY-MM-DD、既定は昨日)")
    args = parser.parse_args()

    settings = Settings()
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    target_date = args.date or _default_target_date(settings)
    asyncio.run(_run(settings, target_date))


if __name__ == "__main__":
    main()
