"""ドメインエンティティ(Hub/Satellite パターン).

`Item` が汎用のハブ、`PaperRecord` が論文ドメイン固有のサテライト。
SQLModel を使い、Pydantic モデルとテーブル定義を一本化する(二重管理を避ける)。

`Chunk` は論文本文の断片、Embedding の実データは SQLModel のテーブルではなく
`db/vector_store.py` が管理する sqlite-vec の vec0 仮想テーブルに入る
(通常の SQLite テーブルとして表現できないため)。`EmbeddingRecord` はその
受け渡し用の非 table モデル。
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ItemType(StrEnum):
    """Item の種別."""

    paper = "paper"
    todo = "todo"
    news_article = "news_article"


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


class MemoryTheme(SQLModel, table=True):
    """チャット長期記憶(017-chat-memory)のテーマ索引.

    想起・抽出それぞれのLLM呼び出しに毎回渡す軽量な一覧(slug + 一行説明)。
    現在状態ファイル本体は`memory/<slug>.md`にあり、ここはその索引のみ持つ。
    """

    __tablename__ = "memory_themes"  # pyright: ignore[reportAssignmentType]

    slug: str = Field(primary_key=True)
    description: str
    updated_at: datetime


class MemoryEvent(SQLModel, table=True):
    """チャット長期記憶のログ層(017-chat-memory). 追記のみ、削除・編集しない.

    現在状態ファイル(`memory/<theme>.md`)はこのログをもとにLLMが都度書き直す
    materialized viewで、ログ自体が真実の記録(event sourcing)。
    """

    __tablename__ = "memory_events"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    theme: str = Field(index=True)
    extracted_at: datetime
    source_conversation_turn: str  # 抽出元になったユーザー発言のAG-UI message id(トレーサビリティ用)
    raw_text: str  # 抽出された記憶内容(このターンで学んだことの短い記述)


class NewsRecord(SQLModel, table=True):
    """ニュース記事ドメイン固有のサテライトテーブル(008-daily-digest-domain Phase A).

    `source_label`は対立軸の定義方針(spec参照)によりフィード単位で静的に決まる
    (ai_llm/swe_general/jp_tech_blog/tech_industry_news)。記事単位のLLM自動分類はしない。
    """

    __tablename__ = "news_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    source_name: str
    source_label: str
    published_at: datetime
    source_url: str = Field(index=True, unique=True)  # 重複防止キー(PaperRecord.source_urlと同じ役割)


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


class DailySummaryRecord(SQLModel, table=True):
    """日次サマリー通知(023-daily-summary-notification)のドメイン固有テーブル.

    `MemoryTheme`/`MemoryEvent`と同じく`Item`ハブは経由しない(特定の知識アイテム
    1件に紐づくものではなく、複数ドメインを横断した1日分のまとめのため)。
    `summary_date`はJST基準の日付(services/daily_summary.pyでUTC範囲に変換して集計する)。
    既読管理はサーバー側に持たず、フロント側のlocalStorageで行う。
    """

    __tablename__ = "daily_summary_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    summary_date: date = Field(index=True, unique=True)  # 1日1件
    content: str
    generated_at: datetime
