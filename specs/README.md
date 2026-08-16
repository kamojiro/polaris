# Specs 一覧・進捗状況

feature単体のspecファイルには書きにくい「spec間の順序・着手可否」をここで管理する。ステータスが変わったら都度更新する。

| # | spec | ステータス | 備考 |
|---|---|---|---|
| 001 | [walking-skeleton](001-walking-skeleton/spec.draft.md) | 🚧 実装中 | バックエンド(FastAPI+AG-UI+SQLite)・フロントエンド(Vite+React+@ag-ui/client)実装済み。実LLMキーでの動作確認待ち |
| 002 | [papers-ingest-full](002-papers-ingest-full/spec.draft.md) | ⏸ 001完了待ち | Embeddingモデル・ストレージ(SQLite/Postgres)が未決定。001が動いてから決める。永続化は SQLModel を採用済み(001参照) |

## ステータスの意味

- ✅ 実装開始可能: 依存・未決定事項なし。`/speckit.specify`等に渡してすぐ着手できる
- ⏸ 待機中: 依存するspecや未決定事項がある。理由を備考に書く
- 🚧 実装中
- ✔️ 完了
