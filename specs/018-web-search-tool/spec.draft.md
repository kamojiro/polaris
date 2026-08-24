# 018. Web検索tool(SearXNG連携)

## ステータス

✅ 実装開始可能

## 概要

チャットエージェント(および将来の前処理/後処理パイプライン)から使える汎用Web検索toolを追加する。自前ホスト済みのSearXNGインスタンスを検索バックエンドとして使う。接続方式はMCPではなく**自前のHTTPクライアント(adapter)**にする(2026-08-23、方針転換。詳細は背景・判断参照)。

## 背景・判断

- 汎用Web検索は複数ドメインから必要とされている: 論文ドメインのセレンディピティ的発見、`007-todo-domain`が将来spec扱いにした現況調査エージェント、`013-ir-analysis-domain`の企業背景確認、`017-chat-memory`の想起・抽出まわりなど。1つ作れば複数specの前提を同時に満たせるため優先度を上げる(`specs/IDEAS.md`参照)
- SearXNGは既に自前ホスト済みで運用中なので、追加のサードパーティ依存・APIキー契約は不要
- **接続方式の再検討(2026-08-23)**: 当初はMCP toolset経由(`SecretiveShell/MCP-searxng`等)を想定していたが、方針転換した。SearXNGの検索エンドポイントは`GET /search?q=...&format=json`1本・認証不要という単純なAPIで、MCPサーバー(サードパーティのサブプロセス、単一メンテナのお守りリスクがある)を挟むメリットが薄い。`adapters/arxiv/client.py`/`adapters/edinet/client.py`と同じ形で`adapters/searxng/client.py`に`httpx`呼び出し1つを書く方が、依存を増やさずシンプルに済む
- これに伴い、`specs/IDEAS.md`の「MCP vs 自前adapter」の判断基準も「汎用インフラ系かどうか」から「APIの複雑さ・信頼できる実装の有無」に整理し直した(`specs/IDEAS.md`参照)。Google Calendar/Gmail(OAuth・複数エンドポイント・複雑なデータ構造、かつ公式MCPがある)はMCP側、SearXNG(単純なGET1本)は自前adapter側、という切り分けになる

## tool設計

- チャットエージェントに`web_search(query)`toolを1つ追加する。`adapters/searxng/client.py::search(query) -> list[SearchResult]`を薄くラップする
- 複数クエリを並列に投げたいユースケース(017の想起判定、007の現況調査等)が具体化したら、`asyncio.gather`で複数リクエストを並列実行すればよい(MCPサーバーを並列対応実装に差し替える必要はない)

## 接続方式

自前adapter(`adapters/searxng/client.py`)による直接HTTP呼び出し。`httpx`で`GET {settings.searxng_url}/search?q=...&format=json`を叩き、結果をパースして返す。MCPは使わない。

SearXNGはコンテナで運用中。`settings.searxng_url`は環境に応じて、Polarisと同じdocker-composeネットワーク内なら`http://searxng:<port>`(サービス名解決)、そうでなければポートマッピング済みの`http://localhost:<port>`を指す想定。追加のプロセス(MCPサーバー等)を挟まないぶん、コンテナ構成もシンプルなまま(SearXNGコンテナ+Polarisコンテナ/プロセスの2者間HTTPのみ)。

## 利用箇所(想定、具体的な組み込みは各specで判断)

- `007-todo-domain`(将来spec: 現況調査エージェント)
- `013-ir-analysis-domain`(企業背景の補助情報取得)
- `017-chat-memory`(想起・抽出の判断材料としての間接利用、将来拡張)
- 論文ドメインのセレンディピティ的発見(具体spec未定)

## 未決定事項

- チャットエージェントに常時toolとして持たせるか、必要なドメインだけに持たせるか
- 検索結果をそのままLLMコンテキストに渡すか、件数・文字数を絞る前処理を挟むか
- SearXNGのレスポンス形式(`format=json`)の具体的なフィールド構成は着手時に実機で確認する

## 依存

- 特になし(SearXNGインスタンスは運用中)
