<!-- /speckit.specify にそのまま渡す下書き。出所: wishlist/requirements/papers-ingest.md -->
<!-- 001-walking-skeleton が動いた後に着手する -->

# 論文Ingestパイプライン(フル版)

001-walking-skeletonのarXivメタデータのみの最小Ingestを拡張し、PDF本文抽出・チャンク分割・Embedding生成まで含むフルのIngestパイプラインを実装する。

## 目的・スコープ

PDF / URL / arXiv を入力として論文を取り込み、`Item`(hub)+ `PaperRecord`(satellite)+ `Chunk` / `Embedding` として永続化する。

対象外: スキャンPDFのOCR、図表・画像の抽出、引用グラフの多段探索(1階層のみ、オプション)、セレンディピティ的な関連付け。

## データモデル

```python
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, HttpUrl


class ItemType(str, Enum):
    paper = "paper"


class Item(BaseModel):
    id: str
    item_type: ItemType
    title: str
    summary: str
    created_at: datetime
    source_ref: str  # "paper:{PaperRecord.id}"


class PaperRecord(BaseModel):
    id: str
    item_id: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    abstract: str
    source_url: HttpUrl | None
    pdf_path: str | None
    ingested_at: datetime


class Chunk(BaseModel):
    id: str
    item_id: str
    section: str | None
    order: int
    text: str


class Embedding(BaseModel):
    chunk_id: str
    vector: list[float]
    model: str
```

## 処理フロー

1. 入力判定(arxiv / url / local_pdf)
2. メタデータ取得(arXiv APIまたはPDFダウンロード)
3. PDF取得・保存
4. 本文抽出(`pypdf` または `unstructured`、失敗時はabstractのみで続行)
5. Structure: Pydantic AIエージェントで欠落メタデータ・要約を生成
6. チャンク分割(セクション単位、フォールバックで固定長)
7. Embedding生成
8. 永続化(Item→PaperRecord→Chunk→Embeddingの順、トランザクション)
9. (オプション)Semantic Scholar APIで引用関係取得

## 重複防止・冪等性

`arxiv_id` / `doi` / `source_url` のいずれかで既存レコードを検索し、あれば新規作成しない。部分的成功(メタデータのみ登録、本文/Embedding未完了)を許容し、再実行で埋められるようにする。

## エラーハンドリング

| 失敗箇所 | 挙動 |
|---|---|
| arXiv API / URL取得失敗 | 例外を投げてIngest全体を失敗させる |
| PDF本文抽出失敗 | warningsに記録し、abstractのみで続行 |
| Structure(LLM抽出)のスキーマ検証失敗 | pydantic-aiの通常retriesに従う(失敗率はeval対象) |
| Embedding生成失敗 | warningsに記録し、Item/PaperRecordは登録済みのまま終了 |

## Embeddingモデル(決定)

`sentence-transformers` 経由で `Qwen/Qwen3-Embedding-0.6B` をローカルGPUでロードして使う(OpenRouter等のAPI経由ではなく自前ホスト)。チャット用のLLM(OpenRouter経由のQwen3-30B-A3B/Qwen3.6-35B-A3B)とは別軸のモデル選択であり、このプロジェクトで初めて「ローカルモデル」を実際に使う箇所になる。

実装時の注意点:
- モデルのロード(`SentenceTransformer(...)`)はアプリ起動時に1回だけ行い、プロセス内でシングルトンとして保持する(呼び出しごとに再ロードしない)
- `model.encode()` は同期・ブロッキング呼び出しのため、async前提のIngestパイプライン/FastAPIハンドラから呼ぶ際は `asyncio.to_thread()` 等でスレッドに逃がし、イベントループを塞がない
- 論文1本分のChunkはまとめてバッチでencodeする(1件ずつ呼ばない)
- `Embedding.model` フィールドに `"Qwen/Qwen3-Embedding-0.6B"` を正確に記録し、将来モデル変更時に再生成対象を判別できるようにする
- Embedding呼び出しは小さなインターフェース(`Protocol`)の裏に隠し、将来API経由の別モデルに切り替え可能にしておく

## 未決定事項

- ストレージ(SQLite vs Postgres、wishlist側の結論に従う)
- チャンク分割の粒度(セクション検出精度次第で調整)

## 完了の定義

- arXiv URLを1件入力すると、Item + PaperRecord + Chunk(1件以上)+ Embedding(1件以上)が永続化される
- 同じarXiv URLを再度入力しても重複登録されない
- PDF本文抽出に失敗しても、abstractベースでメタデータと要約は登録される
