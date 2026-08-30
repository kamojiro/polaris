"""services/diary.py のロジックテスト.

`tests/services/test_memory.py`と同じく、rewriteのLLM呼び出しはフェイクに差し替え、
実LLM依存なしでorchestration(record_diary_turn)のロジックだけを検証する。
"""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from sqlmodel import Session

from polaris.db.diary_repository import DiaryRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import Item
from polaris.services.daily_summary import local_today
from polaris.services.diary import record_diary_turn
from polaris.settings import Settings


class _FakeRewriter:
    """渡されたraw_textsをそのまま連結して返すだけのフェイク書き直しエージェント."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def rewrite(self, *, raw_texts: Sequence[str]) -> str:
        self.calls.append(list(raw_texts))
        return "\n".join(raw_texts)


def _make_repo(tmp_path: Path) -> DiaryRepository:
    return DiaryRepository(create_db_engine(str(tmp_path / "test.db")))


async def test_record_diary_turn_creates_entry_for_today(tmp_path: Path) -> None:
    """1回目の呼び出しで、今日の日付のDiaryRecordが作られる(US1)."""
    repo = _make_repo(tmp_path)
    settings = Settings()
    rewriter = _FakeRewriter()

    await record_diary_turn(
        "今日は散歩に行った", "いいですね", turn_id="turn-1", rewriter=rewriter, repo=repo, settings=settings
    )

    today = local_today(settings.daily_summary.timezone)
    record = repo.get_record(today)
    assert record is not None
    assert "今日は散歩に行った" in record.content
    events = repo.list_events(today)
    assert len(events) == 1
    assert events[0].source_conversation_turn == "turn-1"
    assert "今日は散歩に行った" in events[0].raw_text
    assert "いいですね" in events[0].raw_text


async def test_record_diary_turn_twice_same_day_keeps_single_entry(tmp_path: Path) -> None:
    """同じ日に複数回呼んでも、DiaryRecordは1件のまま両方の内容が反映される(US2)."""
    repo = _make_repo(tmp_path)
    settings = Settings()
    rewriter = _FakeRewriter()

    await record_diary_turn(
        "今日は散歩に行った", "いいですね", turn_id="turn-1", rewriter=rewriter, repo=repo, settings=settings
    )
    await record_diary_turn(
        "夕方には雨が降った", "傘は持ってましたか", turn_id="turn-2", rewriter=rewriter, repo=repo, settings=settings
    )

    today = local_today(settings.daily_summary.timezone)
    record = repo.get_record(today)
    assert record is not None
    assert "今日は散歩に行った" in record.content
    assert "夕方には雨が降った" in record.content
    events = repo.list_events(today)
    turn_count = 2
    assert len(events) == turn_count
    # 2回目のrewriteには、当日の全イベント(1回目+2回目)が渡される。
    assert len(rewriter.calls[-1]) == turn_count


async def test_record_diary_turn_updates_item_summary(tmp_path: Path) -> None:
    """Itemのtitle/summaryも書き直しごとに更新される(古いままにならない)."""
    engine = create_db_engine(str(tmp_path / "test.db"))
    repo = DiaryRepository(engine)
    settings = Settings()
    rewriter = _FakeRewriter()

    await record_diary_turn(
        "散歩した", "いいですね", turn_id="turn-1", rewriter=rewriter, repo=repo, settings=settings
    )
    await record_diary_turn(
        "雨も降った", "大変でしたね", turn_id="turn-2", rewriter=rewriter, repo=repo, settings=settings
    )

    today = local_today(settings.daily_summary.timezone)
    record = repo.get_record(today)
    assert record is not None

    with Session(engine) as session:
        item = session.get(Item, record.item_id)
        assert item is not None
        assert "雨も降った" in item.summary


async def test_record_diary_turn_with_target_date_updates_past_entry_not_today(tmp_path: Path) -> None:
    """target_dateが指定されれば、当日ではなくその日のDiaryRecordが更新される(US4バックフィル)."""
    repo = _make_repo(tmp_path)
    settings = Settings()
    rewriter = _FakeRewriter()
    today = local_today(settings.daily_summary.timezone)
    past_date = today - timedelta(days=7)

    await record_diary_turn(
        "先週の水曜日は飲み会だった",
        "楽しそうですね",
        turn_id="turn-1",
        rewriter=rewriter,
        repo=repo,
        settings=settings,
        target_date=past_date,
    )

    assert repo.get_record(today) is None
    past_record = repo.get_record(past_date)
    assert past_record is not None
    assert "飲み会" in past_record.content


async def test_record_diary_turn_without_target_date_falls_back_to_today(tmp_path: Path) -> None:
    """target_date未指定(None)なら、これまでどおり当日のDiaryRecordが更新される."""
    repo = _make_repo(tmp_path)
    settings = Settings()
    rewriter = _FakeRewriter()

    await record_diary_turn(
        "今日はいい天気だった",
        "よかったですね",
        turn_id="turn-1",
        rewriter=rewriter,
        repo=repo,
        settings=settings,
        target_date=None,
    )

    today = local_today(settings.daily_summary.timezone)
    record = repo.get_record(today)
    assert record is not None
    assert "いい天気" in record.content
