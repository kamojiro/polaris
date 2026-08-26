"""MemoryRepository の永続化テスト(一時 SQLite を使用)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polaris.db.memory_repository import MemoryRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import MemoryEvent


def test_upsert_theme_creates_new_theme(tmp_path: Path) -> None:
    """未存在のslugならテーマ索引が新規作成される."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    now = datetime.now(UTC)

    repo.upsert_theme(slug="local-llm", description="ローカルLLMの話題", updated_at=now)

    themes = repo.list_themes()
    assert len(themes) == 1
    assert themes[0].slug == "local-llm"
    assert themes[0].description == "ローカルLLMの話題"


def test_upsert_theme_overwrites_existing_description(tmp_path: Path) -> None:
    """既存slugならdescription/updated_atが上書きされる(重複作成されない)."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    first = datetime.now(UTC)
    second = first + timedelta(minutes=5)
    repo.upsert_theme(slug="local-llm", description="旧い説明", updated_at=first)

    repo.upsert_theme(slug="local-llm", description="新しい説明", updated_at=second)

    themes = repo.list_themes()
    assert len(themes) == 1
    assert themes[0].description == "新しい説明"
    # SQLiteはtzinfoを保持せずnaive datetimeとして返すため、UTC付与してから比較する。
    assert themes[0].updated_at.replace(tzinfo=UTC) == second


def test_append_event_and_list_events_orders_by_extracted_at(tmp_path: Path) -> None:
    """append_eventで追記したログがlist_eventsでextracted_at昇順に返る."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    base = datetime.now(UTC)
    for i in range(3):
        repo.append_event(
            MemoryEvent(
                id=f"event-{i}",
                theme="local-llm",
                extracted_at=base + timedelta(minutes=2 - i),  # 逆順に追記する
                source_conversation_turn=f"turn-{i}",
                raw_text=f"内容{i}",
            )
        )

    events = repo.list_events("local-llm")

    assert [e.id for e in events] == ["event-2", "event-1", "event-0"]


def test_list_events_filters_by_theme(tmp_path: Path) -> None:
    """list_eventsは指定したtheme以外のイベントを含まない."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    now = datetime.now(UTC)
    repo.append_event(
        MemoryEvent(id="e1", theme="local-llm", extracted_at=now, source_conversation_turn="t1", raw_text="a")
    )
    repo.append_event(
        MemoryEvent(id="e2", theme="mac-setup", extracted_at=now, source_conversation_turn="t2", raw_text="b")
    )

    assert [e.id for e in repo.list_events("local-llm")] == ["e1"]
    assert [e.id for e in repo.list_events("mac-setup")] == ["e2"]


def test_list_themes_returns_empty_when_none_created(tmp_path: Path) -> None:
    """テーマが1件も無ければ空リストを返す(想起・抽出のLLM呼び出しスキップ判定に使う)."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.list_themes() == []
