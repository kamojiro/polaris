"""IR文書(Item + IrRecord)の永続化リポジトリ(013-ir-analysis-domain).

`db/repository.py`(PaperRepository)と同じ session-per-method の形を踏襲する。
Chunk/Embeddingはv1では作らないため、対応するメソッドは無い(spec「データモデル」参照)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, func, or_, select

from polaris.domain.entities import IrRecord, Item

if TYPE_CHECKING:
    from sqlalchemy import Engine


class IrRepository:
    """Item + IrRecord の保存・検索を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def find_by_doc_id(self, doc_id: str) -> tuple[Item, IrRecord] | None:
        """doc_id(EDINETの書類管理番号)で既存レコードを検索する(重複防止に使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.exec(select(IrRecord).where(IrRecord.doc_id == doc_id)).first()
            if record is None:
                return None
            item = session.get(Item, record.item_id)
            if item is None:
                return None
            return item, record

    def save_ir_document(self, item: Item, record: IrRecord) -> None:
        """Item → IrRecord の順で 1 トランザクションとして保存する.

        `expire_on_commit=False` により、呼び出し側が保持する item / record は
        commit 後もセッションから切り離さずそのまま参照できる(save_paperと同じ形)。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(item)
            session.add(record)
            session.commit()

    def list_ir_documents(self, *, limit: int | None = None) -> list[tuple[Item, IrRecord]]:
        """保存済みのIR文書を作成日時の降順で返す(limit指定でSQLのLIMITで絞り込む)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(Item, IrRecord)
                .join(IrRecord, IrRecord.item_id == Item.id)  # type: ignore[arg-type]
                .order_by(Item.created_at.desc())  # type: ignore[union-attr]
            )
            if limit is not None:
                query = query.limit(limit)
            rows = session.exec(query).all()
            return list(rows)

    def search_ir_documents(self, query: str, *, limit: int = 5) -> list[tuple[Item, IrRecord]]:
        """doc_idの完全一致、または企業名/タイトルの部分一致(大小無視)でIR文書を検索する.

        get_ir_full_text がユーザーの自然文からIR文書を特定するための検索
        (search_papersと同じパターン)。作成日時の降順で `limit` 件まで返す。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            query_stmt = (
                select(Item, IrRecord)
                .join(IrRecord, IrRecord.item_id == Item.id)  # type: ignore[arg-type]
                .where(
                    or_(
                        IrRecord.doc_id == query,
                        IrRecord.filer_name.ilike(f"%{query}%"),  # type: ignore[attr-defined]
                        Item.title.ilike(f"%{query}%"),  # type: ignore[attr-defined]
                    )
                )
                .order_by(Item.created_at.desc())  # type: ignore[union-attr]
                .limit(limit)
            )
            rows = session.exec(query_stmt).all()
            return list(rows)

    def count_ir_documents(self) -> int:
        """保存済みのIR文書の総数を返す(一覧の省略表示に使う軽量なカウントのみのクエリ)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(func.count()).select_from(Item).join(IrRecord, IrRecord.item_id == Item.id)  # type: ignore[arg-type]
            return session.exec(query).one()
