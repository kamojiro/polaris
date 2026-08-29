"""DailySummaryRepository の永続化テスト(一時 SQLite を使用)."""

from datetime import UTC, date, datetime
from pathlib import Path

from polaris.db.daily_summary_repository import DailySummaryRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import DailySummaryRecord


def _make_record(
    record_id: str = "rec-1", *, summary_date: date = date(2026, 8, 30), content: str = "今日はこんな日でした。"
) -> DailySummaryRecord:
    return DailySummaryRecord(
        id=record_id, summary_date=summary_date, content=content, generated_at=datetime.now(UTC)
    )


def test_save_and_get_latest(tmp_path: Path) -> None:
    """保存したサマリーがget_latestで取得できる."""
    repo = DailySummaryRepository(create_db_engine(str(tmp_path / "test.db")))

    repo.save(_make_record())
    latest = repo.get_latest()

    assert latest is not None
    assert latest.summary_date == date(2026, 8, 30)
    assert latest.content == "今日はこんな日でした。"


def test_save_upserts_by_summary_date(tmp_path: Path) -> None:
    """同じsummary_dateで2回saveすると上書きされる(CLI再実行時の冪等性)."""
    repo = DailySummaryRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(content="1回目の内容"))

    repo.save(_make_record(record_id="rec-2", content="2回目の内容"))

    latest = repo.get_latest()
    assert latest is not None
    assert latest.content == "2回目の内容"


def test_get_latest_returns_most_recent_date(tmp_path: Path) -> None:
    """複数の日付が保存されている場合、summary_dateが最新のものを返す."""
    repo = DailySummaryRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(record_id="rec-old", summary_date=date(2026, 8, 28)))
    repo.save(_make_record(record_id="rec-new", summary_date=date(2026, 8, 30)))

    latest = repo.get_latest()

    assert latest is not None
    assert latest.summary_date == date(2026, 8, 30)


def test_get_latest_returns_none_when_empty(tmp_path: Path) -> None:
    """1件も保存されていなければNoneを返す."""
    repo = DailySummaryRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.get_latest() is None
