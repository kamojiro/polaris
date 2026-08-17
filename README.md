# Polaris

個人用の知識・生活管理プラットフォーム(実装コードネーム: Polaris)。

設計の経緯・議論のログは `wishlist` フォルダ側にある(`wishlist/wishlist-design.md`, `wishlist/discussion/`)。ここは実装リポジトリで、GitHub Spec Kit を使ったspec-driven developmentで進める想定。

## セットアップ(このマシンで実行する場合)

```bash
cd polaris
uvx --from git+https://github.com/github/spec-kit.git specify init --here
```

Cowork側のサンドボックスはネットワーク制限によりSpec KitのCLIをそのまま実行できなかったため、上記コマンドは実際に使うマシン(git・ネットワークに制限のない環境)側で実行すること。`git init` も同様にこちらで行う。

`specify init` を実行すると `.specify/` とスラッシュコマンド一式が入る。その後、下記の下書きをそのまま(または調整して)`/speckit.constitution` と `/speckit.specify` に渡す。

## ディレクトリ構成

```
docs/
  constitution.draft.md          # /speckit.constitution に渡す下書き
  adr/                            # 後戻りしにくい決定を記録する(実装が進んでから追加)
specs/
  README.md                       # spec一覧と着手可否のステータス表
  001-walking-skeleton/
    spec.draft.md                 # 最初の実装ターゲット。/speckit.specify に渡す下書き
  002-papers-ingest-full/
    spec.draft.md                 # walking skeletonの後に着手するフルIngestパイプライン
```

着手可否は `specs/README.md` を見ればわかる。

`.draft.md` はSpec Kitの正式なテンプレート(`spec.md`/`plan.md`/`tasks.md`)が生成される前の、人間が書いた種(seed)。`/speckit.specify` 等に渡した後は、生成された正式ファイルの方を正とする。

## 起動方法(001-walking-skeleton / 002-papers-ingest-full)

`.specify/` が未初期化のため、`specs/001-walking-skeleton/spec.draft.md` と `specs/002-papers-ingest-full/spec.draft.md` を直接実装したもの。バックエンド(FastAPI + pydantic-ai + AG-UI)とフロントエンド(Vite + React + `@ag-ui/client`)の2つを別々に立ち上げる。

002で「保存」は arXiv URL 入力(URL / ローカルPDFアップロードは範囲外)に対し、PDF取得 → `pypdf` で本文抽出 → pydantic-ai エージェントで要約・venue 生成 → セクション単位のチャンク分割 → `Qwen/Qwen3-Embedding-0.6B`(sentence-transformers、ローカルロード)で Embedding 生成、までのフルパイプラインを行う。永続化先は SQLite 1ファイル(`items`/`paper_records`/`chunks` の通常テーブル + `embeddings` の sqlite-vec vec0 仮想テーブル、ADR-0001)。

### 事前準備

```bash
uv sync                 # Python 依存関係(pypdf, sentence-transformers, sqlite-vec を含む)
cd frontend && npm install && cd ..   # フロントエンド依存関係
```

`sentence-transformers` は初回 `Qwen/Qwen3-Embedding-0.6B` のダウンロードで数百MB〜のディスク・ネットワークを使う(Hugging Face のモデルキャッシュに保存され、以降は再利用される)。GPU が無くても動く(CPUで自動フォールバック)が、その分ロード・エンコードが遅くなる。

`.env` を作り(`.env` は git 管理外)、以下を設定する:

```
LLM__API_KEY=<OpenRouter の API キー>
LLM__BASE_URL=https://openrouter.ai/api/v1
LLM__MODEL_ID=qwen/qwen3-30b-a3b:free
DB_PATH=data/polaris.db

# 002-papers-ingest-full 用(省略時は下記の既定値が使われる)
INGEST__PDF_DIR=data/pdfs
INGEST__EMBEDDING_MODEL_ID=Qwen/Qwen3-Embedding-0.6B
INGEST__EMBEDDING_DIM=1024
INGEST__CHUNK_CHARS=1200
INGEST__CHUNK_OVERLAP_CHARS=200
```

以前の 001 時代の `data/polaris.db` はスキーマが異なる(`venue`/`pdf_path`/`chunks`/`embeddings` が無い)ため、初めて 002 のコードで起動する前に削除しておくこと(`rm -f data/polaris.db`、`.gitignore` 済みなので実害なし)。

### バックエンド

```bash
uv run uvicorn polaris.api.app:app --reload --reload-dir src --host 0.0.0.0 --port 8000
```

`GET /api/health` で疎通確認、`POST /api/chat` が AG-UI のチャットエンドポイント。起動時に Embedding モデルをロードするため、初回起動(モデル未ダウンロード時)は数分かかる。2回目以降はローカルキャッシュを使い `local_files_only=True` でロードするため数秒で立ち上がる(Hugging Face Hub への通信は行わない)。`--host 0.0.0.0` で同一 LAN 上の別デバイスからも到達可能になる(不要ならこのオプションは省略して `127.0.0.1` のみに絞ってよい)。

`--reload-dir src` を付けているのは、`dev` グループの `watchfiles` が無いと uvicorn は原始的な `StatReload`(0.25秒おきに監視対象ディレクトリ配下の `.py` を全部 `stat()` する実装)にフォールバックするため。`sentence-transformers`/`torch` 導入後は `.venv` 配下だけで4万近い `.py` ファイルがあり、`--reload-dir` を指定しないと `.venv` まで監視対象に入ってCPUを張り付かせる(`uv sync` で `watchfiles` が入っていれば効率的な inotify ベースの監視になるが、念のため明示的に絞っている)。

### フロントエンド

```bash
cd frontend
npm run dev              # http://localhost:5173 (バックエンドへは /api を自動プロキシ)
```

`vite.config.ts` の `server.host = true` により、起動時に表示される LAN の URL(例: `http://192.168.0.20:5173`)からも別デバイスでアクセスできる。`/api` プロキシは常にこのマシン上の `localhost:8000` に転送するので、アクセス元デバイスに関係なく動く。

ブラウザでチャットに arXiv の URL(例: `https://arxiv.org/abs/1706.03762`)を貼ると、PDF取得・本文抽出・チャンク分割・Embedding生成まで行われて保存される(チャンク数がメッセージに表示される)。「今まで保存した論文は?」と聞くと一覧が返る。同じ URL をもう一度貼っても重複登録されない。

永続化結果は直接確認できる:

```bash
sqlite3 data/polaris.db "select title, summary from items;"
sqlite3 data/polaris.db "select arxiv_id, venue, pdf_path from paper_records;"
sqlite3 data/polaris.db 'select section, "order" from chunks;'  # order は SQLite 予約語なのでクォートが必要

# embeddings は sqlite-vec の vec0 仮想テーブルなので、CLI から見るには拡張のロードが要る
sqlite3 -cmd ".load $(uv run python -c 'import sqlite_vec; print(sqlite_vec.loadable_path())')" \
  data/polaris.db "select chunk_id, model from embeddings;"
```

### 開発時のチェック

```bash
uv run nox                # ruff lint/format + pyright + pytest (+ cspell)
```
