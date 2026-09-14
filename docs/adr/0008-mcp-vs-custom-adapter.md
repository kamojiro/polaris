# 0008. MCP経由か自前adapterかは、API複雑さと信頼できる実装の有無で判断する

## ステータス

採択

## コンテキスト

外部サービス(検索エンジン、カレンダー、メール等)と連携するtoolを追加するたびに、Model Context Protocol(MCP)サーバーを介するか、`httpx`で自前adapterを書くかの判断が必要になる。`018-web-search-tool`の検討時、当初は「汎用インフラ系はMCP、独自データモデルに紐づくものは自前adapter」という軸で考えていたが、SearXNG連携の検討で見直した。SearXNGの検索エンドポイントは`GET /search?format=json`1本のシンプルなAPIで、「汎用インフラ」ではあってもMCPサブプロセスを挟む理由が乏しかった。

## 決定

「汎用か独自データモデルに紐づくか」ではなく、**APIそのものの複雑さ**と**信頼できる実装の有無**で判断する。

- MCPが向く条件: (a) OAuth・複数エンドポイント・複雑なデータ構造など自前実装が本当に面倒なAPIである、(b) 信頼できる(理想は公式の)実装がある
- 自前adapterが向く条件: 単一エンドポイント・認証なし(または簡単なAPIキー)程度のシンプルなAPIである

## 検討した代替案

- 「汎用インフラ系はMCP、独自データモデルに紐づくものは自前adapter」(当初案): SearXNGのような汎用インフラでも、APIが十分シンプルならMCPサブプロセス(単一メンテナのお守りリスク、パッケージ管理コスト)を挟む理由がなく、この軸では判断を誤ることが分かった。

## 結果(Consequences)

良い面: `018-web-search-tool`は自前adapter方式(当初SearXNG、2026-09-14にTavilyへ移行後も`adapters/tavily/client.py`として踏襲)を採用し、サードパーティMCPサブプロセスを避けられた。バックエンドが変わってもこの判断軸自体は変わらない(APIがシンプルなら自前adapter)。Google Calendar/Gmailのような複雑なAPI(`020-google-workspace-integration`候補)では、公式MCPサーバーの利用が引き続き有力候補として残る。

悪い面: 「複雑さ」「信頼できる実装の有無」はどちらも定量化しにくい主観的判断のため、本ADRだけでは自動的に結論が出ず、都度spec側で個別に判断を書き残す必要がある。EDINET/arXivのようにPolaris独自のデータモデル(Hub/Satellite、冪等性チェック)に深く結びつく取り込みロジックは、どちらの方式を選んでも結局自前adapterに落ち着く(MCPで生データだけ取ってきても、その先の永続化ロジックは自前で書く必要があるため)。

## 関連

- `018-web-search-tool`
- `specs/IDEAS.md`「MCP vs 自前adapter、どちらで実装するか」
- `020-google-workspace-integration`/`021-discord-integration`/`022-misskey-integration`(未着手、この基準が再度問われる見込み)
