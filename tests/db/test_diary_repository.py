"""DiaryRepository の永続化テスト(一時 SQLite を使用、019-diary-domain)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from polaris.db.diary_repository import DiaryRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import DiaryEvent, DiaryRecord, Item, ItemType

_DAY = date(2026, 8, 30)


def _make_repo(tmp_path: Path) -> DiaryRepository:
    return DiaryRepository(create_db_engine(str(tmp_path / "test.db")))


def _make_item(*, item_id: str, title: str, summary: str, created_at: datetime) -> Item:
    return Item(
        id=item_id,
        item_type=ItemType.diary,
        title=title,
        summary=summary,
        created_at=created_at,
        source_ref=f"diary:{_DAY}",
    )


def test_append_event_and_list_events_orders_by_recorded_at(tmp_path: Path) -> None:
    """append_eventで追記したログがlist_eventsでrecorded_at昇順に返る."""
    repo = _make_repo(tmp_path)
    base = datetime.now(UTC)
    for i in range(3):
        repo.append_event(
            DiaryEvent(
                id=f"event-{i}",
                entry_date=_DAY,
                recorded_at=base + timedelta(minutes=2 - i),  # 逆順に追記する
                source_conversation_turn=f"turn-{i}",
                raw_text=f"内容{i}",
            )
        )

    events = repo.list_events(_DAY)

    assert [e.id for e in events] == ["event-2", "event-1", "event-0"]


def test_list_events_filters_by_entry_date(tmp_path: Path) -> None:
    """list_eventsは指定した日付以外のイベントを含まない."""
    repo = _make_repo(tmp_path)
    now = datetime.now(UTC)
    repo.append_event(
        DiaryEvent(id="e1", entry_date=_DAY, recorded_at=now, source_conversation_turn="t1", raw_text="a")
    )
    repo.append_event(
        DiaryEvent(
            id="e2", entry_date=_DAY - timedelta(days=1), recorded_at=now, source_conversation_turn="t2", raw_text="b"
        )
    )

    assert [e.id for e in repo.list_events(_DAY)] == ["e1"]


def test_upsert_record_creates_new_entry(tmp_path: Path) -> None:
    """未存在のentry_dateならItem+DiaryRecordが新規作成される."""
    repo = _make_repo(tmp_path)
    now = datetime.now(UTC)
    item = _make_item(item_id="item-1", title=f"{_DAY}の日記", summary="散歩した", created_at=now)
    record = DiaryRecord(id="record-1", item_id="item-1", entry_date=_DAY, content="今日は散歩した", updated_at=now)

    repo.upsert_record(item, record)

    fetched = repo.get_record(_DAY)
    assert fetched is not None
    assert fetched.content == "今日は散歩した"


def test_upsert_record_updates_existing_entry_without_duplicating(tmp_path: Path) -> None:
    """既存entry_dateならDiaryRecordのcontent/updated_atとItemのtitle/summaryが更新され、行は増えない."""
    engine = create_db_engine(str(tmp_path / "test.db"))
    repo = DiaryRepository(engine)
    first = datetime.now(UTC)
    second = first + timedelta(hours=3)
    item1 = _make_item(item_id="item-1", title=f"{_DAY}の日記", summary="散歩した", created_at=first)
    record1 = DiaryRecord(id="record-1", item_id="item-1", entry_date=_DAY, content="今日は散歩した", updated_at=first)
    repo.upsert_record(item1, record1)

    item2 = _make_item(
        item_id="item-1", title=f"{_DAY}の日記", summary="散歩して雨も降った", created_at=first
    )
    record2 = DiaryRecord(
        id="record-1",
        item_id="item-1",
        entry_date=_DAY,
        content="今日は散歩して、夕方には雨も降った",
        updated_at=second,
    )
    repo.upsert_record(item2, record2)

    fetched = repo.get_record(_DAY)
    assert fetched is not None
    assert fetched.content == "今日は散歩して、夕方には雨も降った"

    with Session(engine) as session:
        rows = session.exec(select(DiaryRecord).where(DiaryRecord.entry_date == _DAY)).all()
        assert len(rows) == 1  # entry_dateがunique制約のため、2回upsertしても行は1件のまま
        item = session.get(Item, "item-1")
        assert item is not None
        assert item.summary == "散歩して雨も降った"  # Item.summaryも更新される(2回目以降古いままにならない)


def test_get_record_returns_none_when_missing(tmp_path: Path) -> None:
    """未存在のentry_dateはNoneを返す."""
    repo = _make_repo(tmp_path)

    assert repo.get_record(_DAY) is None


def _save_record(repo: DiaryRepository, *, entry_date: date, content: str, updated_at: datetime) -> None:
    item_id = f"item-{entry_date}"
    item = Item(
        id=item_id,
        item_type=ItemType.diary,
        title=f"{entry_date}の日記",
        summary=content,
        created_at=updated_at,
        source_ref=f"diary:{entry_date}",
    )
    record = DiaryRecord(
        id=f"record-{entry_date}", item_id=item_id, entry_date=entry_date, content=content, updated_at=updated_at
    )
    repo.upsert_record(item, record)


def test_list_records_in_range_includes_boundaries_and_excludes_outside(tmp_path: Path) -> None:
    """list_records_in_rangeは範囲の両端を含み、範囲外は含まない(US5)."""
    repo = _make_repo(tmp_path)
    now = datetime.now(UTC)
    _save_record(repo, entry_date=date(2026, 8, 28), content="範囲外(前)", updated_at=now)
    _save_record(repo, entry_date=date(2026, 8, 29), content="開始日", updated_at=now)
    _save_record(repo, entry_date=date(2026, 8, 30), content="終了日", updated_at=now)
    _save_record(repo, entry_date=date(2026, 8, 31), content="範囲外(後)", updated_at=now)

    records = repo.list_records_in_range(date(2026, 8, 29), date(2026, 8, 30))

    assert [r.entry_date for r in records] == [date(2026, 8, 29), date(2026, 8, 30)]


def test_get_latest_updated_record_returns_most_recently_updated(tmp_path: Path) -> None:
    """get_latest_updated_recordはentry_dateではなくupdated_atが最新のものを返す(バックフィル対応、US6)."""
    repo = _make_repo(tmp_path)
    older_update = datetime.now(UTC)
    newer_update = older_update + timedelta(hours=1)
    # 日付としては8/25の方が古いが、更新されたのは8/30より後(バックフィル)。
    _save_record(repo, entry_date=date(2026, 8, 30), content="8/30分", updated_at=older_update)
    _save_record(repo, entry_date=date(2026, 8, 25), content="バックフィルで8/25に追記", updated_at=newer_update)

    anchor = repo.get_latest_updated_record()

    assert anchor is not None
    assert anchor.entry_date == date(2026, 8, 25)


def test_list_records_before_returns_descending_entries_before_given_date(tmp_path: Path) -> None:
    """list_records_beforeは指定日未満のエントリをentry_date降順でlimit件返す(US6)."""
    repo = _make_repo(tmp_path)
    now = datetime.now(UTC)
    for day in (26, 27, 28, 29):
        _save_record(repo, entry_date=date(2026, 8, day), content=f"8/{day}", updated_at=now)

    records = repo.list_records_before(date(2026, 8, 29), limit=2)

    assert [r.entry_date for r in records] == [date(2026, 8, 28), date(2026, 8, 27)]
