"""TodoRepository の永続化テスト(一時 SQLite を使用)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polaris.db.session import create_db_engine
from polaris.db.todo_repository import TodoRepository
from polaris.domain.entities import Item, ItemType, TodoRecord, TodoScale


def _make_todo(
    todo_id: str = "todo-1",
    *,
    scale: TodoScale = TodoScale.day,
    title: str = "部屋の掃除",
    description: str = "",
    updated_at: datetime | None = None,
) -> tuple[Item, TodoRecord]:
    now = updated_at or datetime.now(UTC)
    item = Item(
        id=f"item-{todo_id}",
        item_type=ItemType.todo,
        title=title,
        summary=description,
        created_at=now,
        source_ref=f"todo:rec-{todo_id}",
    )
    record = TodoRecord(
        id=f"rec-{todo_id}",
        item_id=f"item-{todo_id}",
        scale=scale,
        updated_at=now,
    )
    return item, record


def test_save_and_list_todos(tmp_path: Path) -> None:
    """保存したTODOが一覧に反映される."""
    repo = TodoRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_todo(title="部屋の掃除", description="週末に")

    repo.save_todo(item, record)
    todos = repo.list_todos()

    assert len(todos) == 1
    got_item, got_record = todos[0]
    assert got_item.title == "部屋の掃除"
    assert got_item.summary == "週末に"
    assert got_record.scale == TodoScale.day
    assert got_record.done is False


def test_list_todos_orders_by_updated_at_ascending(tmp_path: Path) -> None:
    """最終更新日が古い(熟成度が高い)ものが先頭に来る."""
    repo = TodoRepository(create_db_engine(str(tmp_path / "test.db")))
    base = datetime.now(UTC)
    for i in range(3):
        item, record = _make_todo(f"todo-{i}", updated_at=base + timedelta(minutes=i))
        repo.save_todo(item, record)

    todos = repo.list_todos()

    assert [item.id for item, _ in todos] == ["item-todo-0", "item-todo-1", "item-todo-2"]


def test_list_todos_filters_by_scale(tmp_path: Path) -> None:
    """Scale を指定するとそのバケットのみ返る."""
    repo = TodoRepository(create_db_engine(str(tmp_path / "test.db")))
    day_item, day_record = _make_todo("todo-day", scale=TodoScale.day)
    month_item, month_record = _make_todo("todo-month", scale=TodoScale.month)
    repo.save_todo(day_item, day_record)
    repo.save_todo(month_item, month_record)

    todos = repo.list_todos(scale=TodoScale.month)

    assert len(todos) == 1
    assert todos[0][0].id == "item-todo-month"


def test_list_todos_excludes_done_by_default(tmp_path: Path) -> None:
    """完了済みTODOは include_done=False(既定)では一覧に出ない."""
    repo = TodoRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_todo()
    repo.save_todo(item, record)
    record.done = True
    repo.update_todo_record(record)

    assert repo.list_todos() == []
    assert len(repo.list_todos(include_done=True)) == 1


def test_get_by_item_id_returns_none_when_missing(tmp_path: Path) -> None:
    """未保存の item_id は None を返す."""
    repo = TodoRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.get_by_item_id("does-not-exist") is None


def test_update_item_and_update_todo_record_persist_changes(tmp_path: Path) -> None:
    """update_item/update_todo_record で編集内容が反映される."""
    repo = TodoRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_todo(title="旧タイトル")
    repo.save_todo(item, record)

    found = repo.get_by_item_id(item.id)
    assert found is not None
    got_item, got_record = found
    got_item.title = "新タイトル"
    got_record.scale = TodoScale.life
    repo.update_item(got_item)
    repo.update_todo_record(got_record)

    reloaded = repo.get_by_item_id(item.id)
    assert reloaded is not None
    assert reloaded[0].title == "新タイトル"
    assert reloaded[1].scale == TodoScale.life


def test_delete_todo_removes_item_and_record(tmp_path: Path) -> None:
    """delete_todo でItem/TodoRecordの両方が削除される."""
    repo = TodoRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_todo()
    repo.save_todo(item, record)

    repo.delete_todo(item.id)

    assert repo.get_by_item_id(item.id) is None
    assert repo.list_todos(include_done=True) == []
