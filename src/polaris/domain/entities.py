"""ドメインエンティティ(Hub/Satellite パターン).

`Item` が汎用のハブ、`PaperRecord` が論文ドメイン固有のサテライト。
SQLModel を使い、Pydantic モデルとテーブル定義を一本化する(二重管理を避ける)。

`Chunk` は論文本文の断片、Embedding の実データは SQLModel のテーブルではなく
`db/vector_store.py` が管理する sqlite-vec の vec0 仮想テーブルに入る
(通常の SQLite テーブルとして表現できないため)。`EmbeddingRecord` はその
受け渡し用の非 table モデル。
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ItemType(StrEnum):
    """Item の種別."""

    paper = "paper"
    todo = "todo"


class Item(SQLModel, table=True):
    """知識アイテムのハブテーブル."""

    __tablename__ = "items"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_type: ItemType
    title: str
    summary: str
    created_at: datetime
    source_ref: str  # "paper:{PaperRecord.id}"


class PaperRecord(SQLModel, table=True):
    """論文ドメイン固有のサテライトテーブル."""

    __tablename__ = "paper_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    authors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = Field(default=None, index=True, unique=True)
    abstract: str = ""
    source_url: str | None = None
    pdf_path: str | None = None
    ingested_at: datetime


class Chunk(SQLModel, table=True):
    """論文本文をセクション単位または固定長で分割した断片."""

    __tablename__ = "chunks"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    section: str | None = None
    order: int
    text: str


class EmbeddingRecord(BaseModel):
    """Chunk の Embedding(sqlite-vec の vec0 仮想テーブルへの受け渡し用、非 table)."""

    chunk_id: str
    vector: list[float]
    model: str


class TodoScale(StrEnum):
    """TODOの時間スケール(バケット)."""

    day = "day"
    month = "month"
    life = "life"


class TodoRecord(SQLModel, table=True):
    """TODOドメイン固有のサテライトテーブル(007-todo-domain).

    タイトルは `Item.title`、詳細メモは `Item.summary` を流用する
    (論文ドメインが `Item.summary` に要約を入れているのと同じ使い方)。
    """

    __tablename__ = "todo_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    scale: TodoScale
    done: bool = False
    updated_at: datetime  # 熟成度(優先度)算出の基準。編集・完了のたびに更新する
    completed_at: datetime | None = None
