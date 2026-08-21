"""services/todo.py(純ロジック)のテスト."""

from polaris.domain.entities import ItemType, TodoScale
from polaris.services.todo import build_todo_records


def test_build_todo_records_links_item_and_record() -> None:
    """Item.id と TodoRecord.item_id が一致し、フィールドが正しく設定される."""
    item, record = build_todo_records(title="部屋の掃除", scale=TodoScale.day, description="週末に")

    assert item.item_type == ItemType.todo
    assert item.title == "部屋の掃除"
    assert item.summary == "週末に"
    assert record.scale == TodoScale.day
    assert record.done is False
    assert record.completed_at is None
    assert record.item_id == item.id
    assert item.source_ref == f"todo:{record.id}"


def test_build_todo_records_generates_unique_ids() -> None:
    """呼び出すたびに異なるIDが生成される."""
    item1, _ = build_todo_records(title="A", scale=TodoScale.month, description="")
    item2, _ = build_todo_records(title="B", scale=TodoScale.month, description="")

    assert item1.id != item2.id
