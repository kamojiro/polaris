"""MemoryHousekeepingRepository の永続化テスト(一時 SQLite を使用)."""

from datetime import UTC, datetime
from pathlib import Path

from polaris.db.memory_housekeeping_repository import MemoryHousekeepingRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import MemoryHousekeepingSuggestion

_GENERATED_AT = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)


def _make_suggestion(
    suggestion_id: str = "sug-1",
    *,
    suggestion_type: str = "merge",
    target_themes: str = "theme-a,theme-b",
    detail: str = "テーマAとテーマBは内容が重複しています。",
    generated_at: datetime = _GENERATED_AT,
) -> MemoryHousekeepingSuggestion:
    return MemoryHousekeepingSuggestion(
        id=suggestion_id, suggestion_type=suggestion_type, target_themes=target_themes, detail=detail,
        generated_at=generated_at,
    )


def test_replace_all_then_list_latest(tmp_path: Path) -> None:
    """replace_allで保存した提案がlist_latestで取得できる."""
    repo = MemoryHousekeepingRepository(create_db_engine(str(tmp_path / "test.db")))

    repo.replace_all([_make_suggestion()])
    latest = repo.list_latest()

    assert len(latest) == 1
    assert latest[0].suggestion_type == "merge"
    assert latest[0].target_themes == "theme-a,theme-b"


def test_replace_all_discards_previous_batch(tmp_path: Path) -> None:
    """新しいバッチでreplace_allすると、前回分は残らず新しい内容だけになる(FR-005)."""
    repo = MemoryHousekeepingRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.replace_all([_make_suggestion(suggestion_id="old-1", suggestion_type="merge")])

    repo.replace_all([_make_suggestion(suggestion_id="new-1", suggestion_type="stale")])

    latest = repo.list_latest()
    assert len(latest) == 1
    assert latest[0].id == "new-1"
    assert latest[0].suggestion_type == "stale"


def test_replace_all_with_empty_list_clears_existing(tmp_path: Path) -> None:
    """空リストでreplace_allすると、既存の候補が消去される(FR-006: 候補0件になったら消去)."""
    repo = MemoryHousekeepingRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.replace_all([_make_suggestion()])

    repo.replace_all([])

    assert repo.list_latest() == []


def test_list_latest_returns_empty_when_never_run(tmp_path: Path) -> None:
    """一度もバッチが実行されていなければ空リストを返す."""
    repo = MemoryHousekeepingRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.list_latest() == []
