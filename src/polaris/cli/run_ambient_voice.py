"""常時音声認識バッチ(026-voice-input Stage2代替案)のCLIエントリポイント.

`uv run python -m polaris.cli.run_ambient_voice` で実行する。008/023/027と同じ
OS cron駆動のCLI。クライアントは`max_wait_seconds`(既定60秒)ごとにチャンクを
フラッシュするため、027(30分間隔)より短い間隔で回す想定
(例: crontabに`*/5 * * * * cd /path/to/polaris && uv run python -m polaris.cli.run_ambient_voice`)。
1回の実行で`settings.ambient_voice.max_records_per_run`件(既定5件)を消化する。
`--max-records`でデバッグ時だけ上書きできる。

`settings.ambient_voice.enabled`が`False`の場合は、何もせず即座に終了する
(常時マイクオンという性質上、誤って有効化しない設計のオプトイン機能)。

FastAPIサーバーの生存に依存させないため、`api/app.py`とは別にEngine・Repository・
Agentを自前で組み立てる。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from polaris.agent.ambient_voice_judge import AgentAmbientVoiceJudge, build_ambient_voice_judge_agent
from polaris.db.ambient_voice_repository import AmbientVoiceRepository
from polaris.db.session import create_db_engine
from polaris.services.ambient_voice import run_ambient_voice_batch
from polaris.settings import Settings

logger = logging.getLogger(__name__)


async def _run(settings: Settings, *, max_records: int | None) -> None:
    engine = create_db_engine(settings.DB_PATH, embedding_dim=settings.ingest.embedding_dim)
    repo = AmbientVoiceRepository(engine)
    judge = AgentAmbientVoiceJudge(build_ambient_voice_judge_agent(settings))

    result = await run_ambient_voice_batch(repo=repo, judge=judge, settings=settings, max_records=max_records)
    logger.info(
        "常時音声認識バッチ完了: reclaimed=%d, processed=%d, done=%d, failed=%d, reacted=%d",
        result.reclaimed,
        result.processed,
        result.done,
        result.failed,
        result.reacted,
    )


def main() -> None:
    """`python -m polaris.cli.run_ambient_voice` のエントリポイント."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-records", type=int, default=None, help="このバッチで消化する最大件数(既定は設定値)"
    )
    args = parser.parse_args()

    settings = Settings()
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not settings.ambient_voice.enabled:
        logger.info("常時音声認識機能が無効(ambient_voice.enabled=false)のため、バッチをスキップします")
        return

    asyncio.run(_run(settings, max_records=args.max_records))


if __name__ == "__main__":
    main()
