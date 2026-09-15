"""常時音声認識のオーケストレーション(026-voice-input Stage2代替案).

判定(`agent/ambient_voice_judge.py`)を1チャンク分実行し、`cli/run_ambient_voice.py`から
呼ばれる。`services/paper_research.py`と同じ「1件の失敗でバッチ全体を落とさない」方針。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from polaris.agent.ambient_voice_judge import AmbientVoiceJudge
    from polaris.db.ambient_voice_repository import AmbientVoiceRepository
    from polaris.domain.entities import AmbientVoiceChunkRecord
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

__all__ = ["AmbientVoiceBatchResult", "run_ambient_voice_batch", "run_one_chunk"]


class AmbientVoiceBatchResult(NamedTuple):
    """`run_ambient_voice_batch` の戻り値(バッチ実行の統計)."""

    reclaimed: int
    processed: int
    done: int
    failed: int
    reacted: int


async def run_one_chunk(
    record: AmbientVoiceChunkRecord,
    *,
    repo: AmbientVoiceRepository,
    judge: AmbientVoiceJudge,
) -> tuple[bool, str]:
    """1件のチャンクを判定する.

    直前に完了したチャンクの`comment`を`previous_comment`として渡し、話題の継続性を
    LLMに緩く判断させる(017の想起・027のtriageと同じ「LLM任せの緩い分類」方針)。
    例外は呼び出し側(`run_ambient_voice_batch`)がcatchして`mark_failed`する想定で、
    ここでは握りつぶさない。
    """
    previous_comment = repo.get_latest_done_comment()
    judgment = await judge.judge(transcript=record.transcript, previous_comment=previous_comment)
    return judgment.worth_reacting, judgment.comment


async def run_ambient_voice_batch(
    *,
    repo: AmbientVoiceRepository,
    judge: AmbientVoiceJudge,
    settings: Settings,
    max_records: int | None = None,
) -> AmbientVoiceBatchResult:
    """キューのstale回収→多重起動ガード→`max_records`件の処理、を1回のバッチとして行う.

    `max_records`を省略した場合は`settings.ambient_voice.max_records_per_run`を使う
    (CLIの`--max-records`でデバッグ時だけ上書きできるようにするための引数)。
    """
    if max_records is None:
        max_records = settings.ambient_voice.max_records_per_run
    now = datetime.now(UTC)
    reclaimed = repo.reclaim_stale(
        now=now,
        older_than_minutes=settings.ambient_voice.stale_in_progress_minutes,
        max_attempts=settings.ambient_voice.max_record_attempts,
    )
    if repo.has_fresh_in_progress(now=now, older_than_minutes=settings.ambient_voice.stale_in_progress_minutes):
        logger.info("実行中の判定があるため、このバッチはスキップします")
        return AmbientVoiceBatchResult(reclaimed=reclaimed, processed=0, done=0, failed=0, reacted=0)

    processed = done = failed = reacted = 0
    for _ in range(max_records):
        record = repo.claim_next_pending(now=datetime.now(UTC))
        if record is None:
            break
        processed += 1
        try:
            worth_reacting, comment = await run_one_chunk(record, repo=repo, judge=judge)
        except Exception as exc:
            logger.exception("チャンクの判定に失敗しました: chunk_id=%s", record.id)
            repo.mark_failed(record.id, error=str(exc)[:500], completed_at=datetime.now(UTC))
            failed += 1
            continue
        repo.mark_done(
            record.id,
            worth_reacting=worth_reacting,
            comment=comment if worth_reacting else None,
            completed_at=datetime.now(UTC),
        )
        done += 1
        if worth_reacting:
            reacted += 1
    return AmbientVoiceBatchResult(reclaimed=reclaimed, processed=processed, done=done, failed=failed, reacted=reacted)
