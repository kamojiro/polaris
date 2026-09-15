"""services/ambient_voice.py のロジックテスト.

judgeエージェント呼び出しはフェイク(`tests/services/test_paper_research.py`の
フェイク構造化エージェントと同じやり方)に差し替え、実LLM・実DBファイルへの依存なしで
オーケストレーション(run_ambient_voice_batch)のロジックだけを検証する。
"""

from datetime import UTC, datetime
from pathlib import Path

from polaris.agent.ambient_voice_judge import AmbientVoiceJudgment
from polaris.db.ambient_voice_repository import AmbientVoiceRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import AmbientVoiceChunkRecord
from polaris.services.ambient_voice import run_ambient_voice_batch
from polaris.settings import AmbientVoiceSettings, Settings

_NOW = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)


class _FakeJudge:
    """固定または順送りのAmbientVoiceJudgmentを返すフェイク(渡された引数を記録する)."""

    def __init__(self, judgments: list[AmbientVoiceJudgment]) -> None:
        self._judgments = judgments
        self.calls: list[tuple[str, str | None]] = []

    async def judge(self, *, transcript: str, previous_comment: str | None) -> AmbientVoiceJudgment:
        self.calls.append((transcript, previous_comment))
        return self._judgments[len(self.calls) - 1]


class _FailingJudge:
    """特定のtranscriptで例外を送出する以外は固定結果を返すフェイク."""

    def __init__(self, *, fail_transcript: str) -> None:
        self._fail_transcript = fail_transcript
        self.calls: list[str] = []

    async def judge(self, *, transcript: str, previous_comment: str | None) -> AmbientVoiceJudgment:
        del previous_comment
        self.calls.append(transcript)
        if transcript == self._fail_transcript:
            msg = "LLM呼び出し失敗"
            raise RuntimeError(msg)
        return AmbientVoiceJudgment(worth_reacting=False, comment="")


def _settings(**overrides: object) -> Settings:
    return Settings(ambient_voice=AmbientVoiceSettings(**overrides))  # type: ignore[arg-type]


def _make_record(record_id: str, *, transcript: str) -> AmbientVoiceChunkRecord:
    return AmbientVoiceChunkRecord(id=record_id, transcript=transcript, status="pending", created_at=_NOW)


async def test_batch_marks_done_with_judgment_result(tmp_path: Path) -> None:
    """判定結果(worth_reacting/comment)がmark_doneに反映される."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("chunk-1", transcript="週末どこか旅行に行きたいな"))
    judge = _FakeJudge([AmbientVoiceJudgment(worth_reacting=True, comment="近場の温泉地はいかがですか")])

    result = await run_ambient_voice_batch(repo=repo, judge=judge, settings=_settings(max_records_per_run=1))

    assert result == (0, 1, 1, 0, 1)
    reaction = repo.get_latest_reaction()
    assert reaction is not None
    assert reaction.comment == "近場の温泉地はいかがですか"


async def test_batch_does_not_persist_comment_when_not_worth_reacting(tmp_path: Path) -> None:
    """worth_reacting=Falseのときcommentは保存しない(mark_doneにNoneを渡す)."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("chunk-1", transcript="んー、そうだねえ"))
    judge = _FakeJudge([AmbientVoiceJudgment(worth_reacting=False, comment="")])

    result = await run_ambient_voice_batch(repo=repo, judge=judge, settings=_settings(max_records_per_run=1))

    assert result.reacted == 0
    assert repo.get_latest_reaction() is None


async def test_batch_passes_previous_comment_for_topic_continuity(tmp_path: Path) -> None:
    """直前に完了したチャンクのcommentがprevious_commentとしてjudgeに渡される."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("chunk-1", transcript="RAGについて調べてる"))
    judge = _FakeJudge([AmbientVoiceJudgment(worth_reacting=True, comment="RAGの基本構成を紹介しました")])
    await run_ambient_voice_batch(repo=repo, judge=judge, settings=_settings(max_records_per_run=1))

    repo.save(_make_record("chunk-2", transcript="その続きでベクトル検索の話"))
    await run_ambient_voice_batch(repo=repo, judge=judge, settings=_settings(max_records_per_run=1))

    assert judge.calls[0] == ("RAGについて調べてる", None)
    assert judge.calls[1] == ("その続きでベクトル検索の話", "RAGの基本構成を紹介しました")


async def test_one_chunk_failure_does_not_abort_batch(tmp_path: Path) -> None:
    """1チャンクの判定失敗はmark_failedにして、残りのチャンクは処理を続行する."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("chunk-bad", transcript="壊れるやつ"))
    repo.save(_make_record("chunk-ok", transcript="普通のやつ"))
    judge = _FailingJudge(fail_transcript="壊れるやつ")

    result = await run_ambient_voice_batch(repo=repo, judge=judge, settings=_settings(max_records_per_run=2))

    assert result.processed == 2  # noqa: PLR2004
    assert result.failed == 1
    assert result.done == 1


async def test_batch_skips_when_fresh_in_progress_exists(tmp_path: Path) -> None:
    """実行中(stale化していない)チャンクがあれば、このバッチは何もしない多重起動ガード."""
    repo = AmbientVoiceRepository(create_db_engine(str(tmp_path / "test.db")))
    # run_ambient_voice_batch内部は datetime.now(UTC)(実時刻)でstale判定するため、
    # 固定の_NOWではなく実行時刻を使う(実時刻基準で「開始直後」を再現する)。
    just_started = datetime.now(UTC)
    repo.save(
        AmbientVoiceChunkRecord(
            id="chunk-running",
            transcript="処理中",
            status="in_progress",
            created_at=just_started,
            started_at=just_started,
        )
    )
    judge = _FakeJudge([AmbientVoiceJudgment(worth_reacting=False, comment="")])

    result = await run_ambient_voice_batch(
        repo=repo, judge=judge, settings=_settings(stale_in_progress_minutes=10, max_records_per_run=1)
    )

    assert result.processed == 0
    assert judge.calls == []
