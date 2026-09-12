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
    ir_document = "ir_document"
    diary = "diary"


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


class IrRecord(SQLModel, table=True):
    """IR文書ドメイン固有のサテライトテーブル(013-ir-analysis-domain).

    EDINET(金融庁の開示書類システム)から取り込んだ有価証券報告書等のPDF
    1件に対応する。`doc_id`はEDINETの書類管理番号(`S100XXXX`のような形式)で、
    `PaperRecord.arxiv_id`と同じ役割の自然キー・重複防止キー。Chunk/Embeddingは
    v1では作らない(spec「データモデル」参照、都度PDF再抽出して全文をチャットに
    渡す方式のみで賄う)。
    """

    __tablename__ = "ir_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    doc_id: str = Field(index=True, unique=True)  # EDINETのdocID(書類管理番号)。重複防止キー
    filer_name: str  # 提出者名(企業名)
    edinet_code: str | None = None
    doc_type_code: str | None = None  # 有価証券報告書/四半期報告書等の種別コード
    period_start: date | None = None
    period_end: date | None = None
    submit_datetime: datetime
    pdf_path: str | None = None
    ingested_at: datetime


class DiaryRecord(SQLModel, table=True):
    """日記ドメイン(019-diary-domain)の現在状態層(satellite).

    `Item`ハブを経由する(将来の全文チャット方式での想起に備えた設計、`spec.draft.md`参照)。
    `content`は`DiaryEvent`ログをもとにLLMが都度書き直すmaterialized view。ファイルではなく
    DBカラムに留めているのは、v1では想起機能(このファイルを読む消費者)自体が無いため
    (research.md Decision 2)。
    """

    __tablename__ = "diary_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    entry_date: date = Field(index=True, unique=True)  # 1日1エントリ、JST基準
    content: str
    updated_at: datetime


class DiaryEvent(SQLModel, table=True):
    """日記ドメインのログ層(019-diary-domain). 追記のみ、削除・編集しない.

    `MemoryEvent`と同型(`theme`が`entry_date`に置き換わる)。日記モード中の会話は
    「記憶に値するか」の選別を行わず無条件に追記する(017との違い、research.md Decision 3)。
    """

    __tablename__ = "diary_events"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    entry_date: date = Field(index=True)
    recorded_at: datetime
    source_conversation_turn: str  # AG-UIメッセージid(トレーサビリティ用、MemoryEventと同型)
    raw_text: str  # このターンのuser発言+assistant応答の生テキスト


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


class MemoryHousekeepingSuggestion(SQLModel, table=True):
    """記憶テーマの定期棚卸し(024-memory-theme-housekeeping)の整理提案1件.

    `MemoryTheme`/`DailySummaryRecord`と同じく`Item`ハブは経由しない(複数テーマを横断した
    提案であり、特定の知識アイテム1件に紐づかないため)。バッチ実行のたびに既存の全行が
    削除され、今回の検出結果で完全に置き換えられる(`generated_at`は全行で共通、
    このバッチの実行時刻)。既読管理はサーバー側に持たず、フロント側のlocalStorageで行う。
    """

    __tablename__ = "memory_housekeeping_suggestions"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    suggestion_type: str  # "merge" | "split" | "stale"
    target_themes: str  # 対象テーマのslugをカンマ区切りで保持(シンプルな実装優先)
    detail: str  # 提案の具体的な理由の説明(LLMが生成)
    generated_at: datetime = Field(index=True)


class PaperResearchRecord(SQLModel, table=True):
    """関連論文調査(027-related-paper-research ユーザーストーリー1)の調査依頼1件.

    `MemoryTheme`/`DailySummaryRecord`と同じく`Item`ハブは経由しない(調査という
    「行為」の記録であり、特定の知識アイテム1件を表すものではないため)。
    このコードベース初のstatus列キュー(`status`: "pending" → "in_progress" →
    "done"/"failed")。`claim_next_pending`/`reclaim_stale`が状態を管理する
    (`db/paper_research_repository.py`参照)。`result_summary`に統合結果の本文
    (LLM生成の日本語)が入る。既読管理はサーバー側に持たず、フロント側の
    localStorageで行う(023/024と同じ)。
    """

    __tablename__ = "paper_research_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    seed_item_id: str = Field(foreign_key="items.id", index=True)
    seed_title: str  # 受付時に非正規化(バナーがitems結合なしで表示できる)
    status: str = Field(index=True)  # "pending" | "in_progress" | "done" | "failed"
    attempts: int = 0
    result_summary: str | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PaperDeepAnalysisRecord(SQLModel, table=True):
    """関連論文調査の精読結果(027-related-paper-research)、論文1本につき1行.

    `item_id`にunique制約があり、他の調査から再利用できるキャッシュとして機能する
    (同じ論文を別の調査が再度精読対象にしても、このテーブルにヒットすればLLM抽出も
    取り込みもしない)。`Item`が無い(arXiv IDもオープンアクセスPDFも無い)論文には
    この行を作らない(外部キーを張れないため)。
    """

    __tablename__ = "paper_deep_analysis_records"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True, unique=True)
    problem: str  # この論文が取り組む課題
    solution: str  # この論文が示した解決・知見
    created_at: datetime


class PaperResearchDiscoveredPaper(SQLModel, table=True):
    """関連論文調査が自動取り込みした論文の出自(027-related-paper-research)、論文1本につき1行.

    ユーザーが自分で`save_paper`した論文と区別するためだけに存在する。1調査で
    最大`paper_research.max_deep_read`本が`items`に自動追加されるため、出自を
    残さないと`list_papers`(「今まで保存した論文は?」)・論文一覧UI・023の日次要約が
    調査で取り込んだ論文で埋まってしまう(2026-09-12にユーザー確認)。`items`に
    区別列を足すのはマイグレーション機構が無いこの環境で最も痛い変更のため、
    新規テーブルで出自を持つ方式にした。`item_id`はunique(同じ論文が別の調査で
    再発見されても行は増えない、最初に発見した調査が記録に残る)。ユーザーが後から
    その論文を明示的に`save_paper`したら、この行は削除される(以降ライブラリの
    一員として扱う)。
    """

    __tablename__ = "paper_research_discovered_papers"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True, unique=True)
    research_id: str = Field(foreign_key="paper_research_records.id", index=True)
    discovered_at: datetime
