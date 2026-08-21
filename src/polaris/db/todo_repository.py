"""TODO(Item + TodoRecord)の永続化リポジトリ(007-todo-domain).

`db/repository.py` の `PaperRepository` と同じ「メソッドごとに Session を開く」
パターンを踏襲する。TODOには論文の arxiv_id のような自然キーが無いため、
Item.id をそのまま外部向けの識別子として使う(`list_chunks(item_id)` と同じ考え方)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import Item, TodoRecord

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from polaris.domain.entities import TodoScale


class TodoRepository:
    """Item + TodoRecord の保存・検索を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def save_todo(self, item: Item, record: TodoRecord) -> None:
        """Item → TodoRecord の順で1トランザクションとして保存する(PaperRepository.save_paperと同型)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(item)
            session.add(record)
            session.commit()

    def list_todos(
        self,
        *,
        scale: TodoScale | None = None,
        include_done: bool = False,
    ) -> list[tuple[Item, TodoRecord]]:
        """TODOを一覧する.

        `TodoRecord.updated_at` の昇順(古い=熟成度が高いものを先頭)で返す。
        `scale` を指定するとそのバケットのみ、`include_done=False`(既定)なら
        完了済みを除く。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(Item, TodoRecord)
                .join(TodoRecord, TodoRecord.item_id == Item.id)  # type: ignore[arg-type]
                .order_by(TodoRecord.updated_at.asc())  # type: ignore[union-attr]
            )
            if scale is not None:
                query = query.where(TodoRecord.scale == scale)
            if not include_done:
                query = query.where(TodoRecord.done == False)  # noqa: E712 - SQLAlchemy式ではisと書けない
            rows = session.exec(query).all()
            return list(rows)

    def get_by_item_id(self, item_id: str) -> tuple[Item, TodoRecord] | None:
        """Item.id で TODO を検索する(update/complete/delete tool が対象を引くのに使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.exec(select(TodoRecord).where(TodoRecord.item_id == item_id)).first()
            if record is None:
                return None
            item = session.get(Item, item_id)
            if item is None:
                return None
            return item, record

    def update_item(self, item: Item) -> None:
        """既存の Item を更新する(タイトル・詳細メモの編集に使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.merge(item)
            session.commit()

    def update_todo_record(self, record: TodoRecord) -> None:
        """既存の TodoRecord を更新する(scale/done/completed_at/updated_atの反映に使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.merge(record)
            session.commit()

    def delete_todo(self, item_id: str) -> None:
        """Item・TodoRecordの該当行を削除する(物理削除。復元は対象外)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.exec(select(TodoRecord).where(TodoRecord.item_id == item_id)).first()
            if record is not None:
                session.delete(record)
            item = session.get(Item, item_id)
            if item is not None:
                session.delete(item)
            session.commit()
