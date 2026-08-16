"""ドメインエンティティ(Hub/Satellite パターン).

`Item` が汎用のハブ、`PaperRecord` が論文ドメイン固有のサテライト。
SQLModel を使い、Pydantic モデルとテーブル定義を一本化する(二重管理を避ける)。

001-walking-skeleton の範囲では arXiv メタデータのみを保存する。
PDF本文・チャンク・Embedding は 002-papers-ingest-full で追加する。
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ItemType(StrEnum):
    """Item の種別."""

    paper = "paper"


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
    doi: str | None = None
    arxiv_id: str | None = Field(default=None, index=True, unique=True)
    abstract: str = ""
    source_url: str | None = None
    ingested_at: datetime
