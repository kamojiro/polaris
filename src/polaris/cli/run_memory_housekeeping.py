"""記憶テーマの定期棚卸し(024-memory-theme-housekeeping)のCLIエントリポイント.

`uv run python -m polaris.cli.run_memory_housekeeping` で実行する。`cli/generate_daily_summary.py`
と同じくOS cronから叩く想定だが、対象期間の引数は持たない(常に実行時点の全テーマの現在状態を
評価するため、research.md Decision 6)。想定実行頻度は週1回(spec.md Assumptions参照。頻度自体は
crontab側の設定のみで表現でき、コード側に頻度用の設定値は不要)。

FastAPIサーバーの生存に依存させないため、`api/app.py`とは別にEngine・Repository・Agentを
自前で組み立てる。GPUは使わないため`QwenEmbedder`はロードしない。
"""

from __future__ import annotations

import asyncio
import logging

from polaris.agent.memory_housekeeping import AgentMemoryHousekeepingDetector, build_memory_housekeeping_agent
from polaris.db.memory_housekeeping_repository import MemoryHousekeepingRepository
from polaris.db.memory_repository import MemoryRepository
from polaris.db.session import create_db_engine
from polaris.services.memory_housekeeping import run_memory_housekeeping
from polaris.settings import Settings

logger = logging.getLogger(__name__)


async def _run(settings: Settings) -> None:
    engine = create_db_engine(settings.DB_PATH, embedding_dim=settings.ingest.embedding_dim)
    detector = AgentMemoryHousekeepingDetector(build_memory_housekeeping_agent(settings))

    suggestions = await run_memory_housekeeping(
        detector=detector,
        memory_repo=MemoryRepository(engine),
        housekeeping_repo=MemoryHousekeepingRepository(engine),
        settings=settings,
    )
    logger.info("記憶テーマ棚卸し完了: suggestions=%d", len(suggestions))


def main() -> None:
    """`python -m polaris.cli.run_memory_housekeeping` のエントリポイント."""
    settings = Settings()
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
