"""論文(Item + PaperRecord)の永続化リポジトリ."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import Item, PaperRecord

if TYPE_CHECKING:
    from sqlalchemy import Engine


class PaperRepository:
    """Item + PaperRecord の保存・検索を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def find_by_arxiv_id(self, arxiv_id: str) -> tuple[Item, PaperRecord] | None:
        """arxiv_id で既存レコードを検索する(重複防止に使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.exec(select(PaperRecord).where(PaperRecord.arxiv_id == arxiv_id)).first()
            if record is None:
                return None
            item = session.get(Item, record.item_id)
            if item is None:
                return None
            return item, record

    def save_paper(self, item: Item, record: PaperRecord) -> None:
        """Item → PaperRecord の順で 1 トランザクションとして保存する.

        `expire_on_commit=False` により、呼び出し側が保持する item / record は
        commit 後もセッションから切り離さずそのまま参照できる。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(item)
            session.add(record)
            session.commit()

    def list_papers(self) -> list[tuple[Item, PaperRecord]]:
        """保存済みの論文を作成日時の降順で返す."""
        with Session(self._engine, expire_on_commit=False) as session:
            rows = session.exec(
                select(Item, PaperRecord)
                .join(PaperRecord, PaperRecord.item_id == Item.id)  # type: ignore[arg-type]
                .order_by(Item.created_at.desc())  # type: ignore[union-attr]
            ).all()
            return list(rows)
