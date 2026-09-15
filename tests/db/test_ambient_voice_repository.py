"""AmbientVoiceRepository のテスト(一時SQLite使用、test_paper_research_repository.pyと同じ形)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polaris.db.ambient_voice_repository import AmbientVoiceRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import AmbientVoiceChunkRecord

_NOW = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)


def _make_record(
    record_id: str = "chunk-1",
    *,
    transcript: str = "今日は良い天気だ",
    status: str = "pending",
    attempts: int = 0,
    created_at: datetime = _NOW,
    started_at: datetime | None = None,
) -> AmbientVoiceChunkRecord:
    return AmbientVoiceChunkRecord(
        id=record_id,
        transcript=transcript,
        status=status,
        attempts=attempts,
        created_at=created_at,
        started_at=started_at,
    )


def test_claim_next_pending_picks_oldest_and_marks_in_progress(tmp_path: Path) -> None:
    """最古のpending行を1件claimし、in_progressへ遷移してattemptsを増やす."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("chunk-old", created_at=_NOW))
    repo.save(_make_record("chunk-new", created_at=_NOW + timedelta(minutes=1)))

    claimed = repo.claim_next_pending(now=_NOW + timedelta(hours=1))

    assert claimed is not None
    assert claimed.id == "chunk-old"
    assert claimed.status == "in_progress"
    assert claimed.attempts == 1


def test_claim_next_pending_returns_none_when_empty(tmp_path: Path) -> None:
    """pending行が無ければNoneを返す."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.claim_next_pending(now=_NOW) is None


def test_reclaim_stale_returns_to_pending_within_attempt_limit(tmp_path: Path) -> None:
    """試行回数が上限未満のstale in_progressはpendingへ戻る."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=1, started_at=_NOW))

    changed = repo.reclaim_stale(now=_NOW + timedelta(hours=1), older_than_minutes=10, max_attempts=2)

    assert changed == 1
    reclaimed = repo.claim_next_pending(now=_NOW + timedelta(hours=1))
    assert reclaimed is not None
    assert reclaimed.id == "chunk-1"


def test_reclaim_stale_marks_failed_when_attempts_exhausted(tmp_path: Path) -> None:
    """試行回数が上限に達しているstale in_progressはfailedになる."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=2, started_at=_NOW))

    changed = repo.reclaim_stale(now=_NOW + timedelta(hours=1), older_than_minutes=10, max_attempts=2)

    assert changed == 1
    assert repo.claim_next_pending(now=_NOW + timedelta(hours=1)) is None  # failedはpendingに戻らない


def test_reclaim_stale_ignores_fresh_in_progress(tmp_path: Path) -> None:
    """開始間もないin_progressは回収対象にならない."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=1, started_at=_NOW))

    changed = repo.reclaim_stale(now=_NOW + timedelta(minutes=1), older_than_minutes=10, max_attempts=2)

    assert changed == 0


def test_has_fresh_in_progress(tmp_path: Path) -> None:
    """開始間もないin_progressがあればTrue、stale化していればFalse."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=1, started_at=_NOW))

    assert repo.has_fresh_in_progress(now=_NOW + timedelta(minutes=1), older_than_minutes=10) is True
    assert repo.has_fresh_in_progress(now=_NOW + timedelta(hours=1), older_than_minutes=10) is False


def test_mark_done_sets_worth_reacting_and_comment(tmp_path: Path) -> None:
    """mark_doneでstatus/worth_reacting/comment/completed_atが更新される."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress"))

    repo.mark_done("chunk-1", worth_reacting=True, comment="面白そうな話題ですね", completed_at=_NOW)

    latest = repo.get_latest_reaction()
    assert latest is not None
    assert latest.comment == "面白そうな話題ですね"


def test_mark_failed_sets_error_and_status(tmp_path: Path) -> None:
    """mark_failedでstatus/errorが更新され、get_latest_reactionには出てこない."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress"))

    repo.mark_failed("chunk-1", error="LLM呼び出し失敗", completed_at=_NOW)

    assert repo.get_latest_reaction() is None


def test_get_latest_reaction_excludes_worth_reacting_false(tmp_path: Path) -> None:
    """worth_reacting=Falseの完了行はバナー対象に含まれない."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress"))

    repo.mark_done("chunk-1", worth_reacting=False, comment=None, completed_at=_NOW)

    assert repo.get_latest_reaction() is None


def test_get_latest_reaction_returns_most_recent(tmp_path: Path) -> None:
    """反応価値ありの完了行が複数あれば最新のものを返す."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("chunk-old", status="in_progress"))
    repo.save(_make_record("chunk-new", status="in_progress"))
    repo.mark_done("chunk-old", worth_reacting=True, comment="古い方", completed_at=_NOW)
    repo.mark_done("chunk-new", worth_reacting=True, comment="新しい方", completed_at=_NOW + timedelta(hours=1))

    latest = repo.get_latest_reaction()

    assert latest is not None
    assert latest.id == "chunk-new"


def test_get_latest_done_comment_returns_none_when_no_chunk_completed(tmp_path: Path) -> None:
    """完了済みチャンクが無ければNone(前回コメントが無いケース)."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.get_latest_done_comment() is None


def test_get_latest_done_comment_returns_most_recent_regardless_of_worth_reacting(tmp_path: Path) -> None:
    """直近の完了チャンクのcommentを返す(worth_reacting=Falseでcomment=Noneのケースも含む)."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("chunk-old", status="in_progress"))
    repo.save(_make_record("chunk-new", status="in_progress"))
    repo.mark_done("chunk-old", worth_reacting=True, comment="古い方のコメント", completed_at=_NOW)
    repo.mark_done("chunk-new", worth_reacting=False, comment=None, completed_at=_NOW + timedelta(hours=1))

    assert repo.get_latest_done_comment() is None
