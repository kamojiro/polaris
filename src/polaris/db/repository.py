"""論文(Item + PaperRecord)の永続化リポジトリ."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, func, select

from polaris.db.vector_store import save_embeddings as _save_embeddings
from polaris.domain.entities import Chunk, Item, PaperRecord

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from polaris.domain.entities import EmbeddingRecord


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

    def find_by_source_url(self, source_url: str) -> tuple[Item, PaperRecord] | None:
        """source_url で既存レコードを検索する(arxiv_id を持たない論文の重複防止に使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.exec(select(PaperRecord).where(PaperRecord.source_url == source_url)).first()
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

    def list_papers(self, *, limit: int | None = None) -> list[tuple[Item, PaperRecord]]:
        """保存済みの論文を作成日時の降順で返す.

        `limit` を指定すると SQL の LIMIT で件数を絞る(全件を毎回 DB から読んで
        LLM に渡すと、件数が増えるほど DB 負荷・トークン量とも際限なく増えるため、
        絞り込みは呼び出し側の Python ではなくここで行う)。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(Item, PaperRecord)
                .join(PaperRecord, PaperRecord.item_id == Item.id)  # type: ignore[arg-type]
                .order_by(Item.created_at.desc())  # type: ignore[union-attr]
            )
            if limit is not None:
                query = query.limit(limit)
            rows = session.exec(query).all()
            return list(rows)

    def count_papers(self) -> int:
        """保存済みの論文の総数を返す(一覧の省略表示に使う軽量なカウントのみのクエリ)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(func.count()).select_from(Item).join(PaperRecord, PaperRecord.item_id == Item.id)  # type: ignore[arg-type]
            return session.exec(query).one()

    def update_item(self, item: Item) -> None:
        """既存の Item を更新する(Structure ステップでの summary 更新等に使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.merge(item)
            session.commit()

    def update_paper_record(self, record: PaperRecord) -> None:
        """既存の PaperRecord を更新する(venue/pdf_path の後埋めに使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.merge(record)
            session.commit()

    def save_chunks(self, chunks: list[Chunk]) -> None:
        """本文チャンクをまとめて 1 トランザクションで保存する."""
        with Session(self._engine, expire_on_commit=False) as session:
            for chunk in chunks:
                session.add(chunk)
            session.commit()

    def list_chunks(self, item_id: str) -> list[Chunk]:
        """指定した Item のチャンクを並び順(order)で返す."""
        with Session(self._engine, expire_on_commit=False) as session:
            rows = session.exec(
                select(Chunk).where(Chunk.item_id == item_id).order_by(Chunk.order)  # type: ignore[arg-type]
            ).all()
            return list(rows)

    def save_embeddings(self, records: list[EmbeddingRecord]) -> None:
        """Chunk の Embedding をまとめて sqlite-vec の vec0 テーブルへ保存する."""
        _save_embeddings(self._engine, records)
