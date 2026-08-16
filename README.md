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

## 001-walking-skeleton の起動方法

`.specify/` が未初期化のため、`specs/001-walking-skeleton/spec.draft.md` を直接実装したもの。バックエンド(FastAPI + pydantic-ai + AG-UI)とフロントエンド(Vite + React + `@ag-ui/client`)の2つを別々に立ち上げる。

### 事前準備

```bash
uv sync                 # Python 依存関係
cd frontend && npm install && cd ..   # フロントエンド依存関係
```

`.env` を作り(`.env` は git 管理外)、以下を設定する:

```
LLM__API_KEY=<OpenRouter の API キー>
LLM__BASE_URL=https://openrouter.ai/api/v1
LLM__MODEL_ID=qwen/qwen3-30b-a3b:free
DB_PATH=data/polaris.db
```

### バックエンド

```bash
uv run uvicorn polaris.api.app:app --reload --host 0.0.0.0 --port 8000
```

`GET /api/health` で疎通確認、`POST /api/chat` が AG-UI のチャットエンドポイント。SQLite は `DB_PATH`(既定 `data/polaris.db`)に作成される。`--host 0.0.0.0` で同一 LAN 上の別デバイスからも到達可能になる(不要ならこのオプションは省略して `127.0.0.1` のみに絞ってよい)。

### フロントエンド

```bash
cd frontend
npm run dev              # http://localhost:5173 (バックエンドへは /api を自動プロキシ)
```

`vite.config.ts` の `server.host = true` により、起動時に表示される LAN の URL(例: `http://192.168.0.20:5173`)からも別デバイスでアクセスできる。`/api` プロキシは常にこのマシン上の `localhost:8000` に転送するので、アクセス元デバイスに関係なく動く。

ブラウザでチャットに arXiv の URL(例: `https://arxiv.org/abs/1706.03762`)を貼ると、タイトル・著者・abstract のみが取得されて保存される。「今まで保存した論文は?」と聞くと一覧が返る。

### 開発時のチェック

```bash
uv run nox                # ruff lint/format + pyright + pytest (+ cspell)
```
