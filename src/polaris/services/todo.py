"""TODO(007-todo-domain)のドメインロジック.

CRUDそのものはDB I/Oなので `db/todo_repository.py` に任せ、ここでは「入力から
レコードを組み立てる」という純粋関数だけを置く(`services/ingest_paper.py` の
`_build_metadata_records` と同じ考え方)。更新・完了・削除は単純なフィールド
代入なので、専用のサービス関数は作らず `agent/chat_agent.py` のtool内に
直接書く(YAGNI)。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from polaris.domain.entities import Item, ItemType, TodoRecord

if TYPE_CHECKING:
    from polaris.domain.entities import TodoScale


def build_todo_records(*, title: str, scale: TodoScale, description: str) -> tuple[Item, TodoRecord]:
    """新規TODOの Item / TodoRecord を組み立てる(まだ保存しない)."""
    now = datetime.now(UTC)
    record = TodoRecord(
        id=uuid.uuid4().hex,
        item_id="",  # 直後に確定させる
        scale=scale,
        updated_at=now,
    )
    item = Item(
        id=uuid.uuid4().hex,
        item_type=ItemType.todo,
        title=title,
        summary=description,
        created_at=now,
        source_ref=f"todo:{record.id}",
    )
    record.item_id = item.id
    return item, record
