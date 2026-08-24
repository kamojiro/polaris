# 018. Web検索tool(SearXNG連携)

## ステータス

✅ 実装開始可能

## 概要

チャットエージェント(および将来の前処理/後処理パイプライン)から使える汎用Web検索toolを追加する。自前ホスト済みのSearXNGインスタンスを検索バックエンドとして使い、既存のMCPサーバー実装をpydantic-aiのMCP toolsetとして接続する(自前でSearXNGのHTTP APIクライアントを書かない)。

## 背景・判断

- 汎用Web検索は複数ドメインから必要とされている: 論文ドメインのセレンディピティ的発見、`007-todo-domain`が将来spec扱いにした現況調査エージェント、`013-ir-analysis-domain`の企業背景確認、`017-chat-memory`の想起・抽出まわりなど。1つ作れば複数specの前提を同時に満たせるため優先度を上げる(`specs/IDEAS.md`参照)
- 自前でSearXNG用クライアントを書くのではなく、既存のMCPサーバー実装(例: `SecretiveShell/MCP-searxng`)をpydantic-aiのMCP toolsetとして繋ぐ。`specs/IDEAS.md`の「MCP vs 自前adapter」判断基準でいう「良質な既存MCPサーバーがある汎用インフラ系」に該当するため
- SearXNGは既に自前ホスト済みで運用中なので、追加のサードパーティ依存・APIキー契約は不要

## tool設計

- チャットエージェントに`web_search(query)`相当のtoolを1つ追加する。MCP toolset経由のため、実際のtool名・引数はMCPサーバー側の定義にそのまま従う想定(ラップし直すかは実装時に判断)
- 複数クエリを並列に投げたいユースケース(017の想起判定、007の現況調査等)が具体化したら、並列マルチクエリ対応の実装(例: `jae-jae/searxng-mul-mcp`)への切り替えを検討する。v1は単一クエリで十分

## 接続方式

pydantic-aiのMCP toolsetとして接続する。SearXNG MCPサーバーの起動方式は2通り考えられる。

- `MCPServerStdio`: Polarisのプロセスと同じマシンでサブプロセスとして起動する。追加の常駐プロセス管理が増えない
- `MCPServerStreamableHTTP`: 常駐サービスとして別途立てておき、HTTP経由で接続する(SSEより現行の推奨トランスポート)

v1は`MCPServerStdio`から始める(常駐プロセスを増やさない、YAGNI)。必要になれば常駐化を検討する。

## 利用箇所(想定、具体的な組み込みは各specで判断)

- `007-todo-domain`(将来spec: 現況調査エージェント)
- `013-ir-analysis-domain`(企業背景の補助情報取得)
- `017-chat-memory`(想起・抽出の判断材料としての間接利用、将来拡張)
- 論文ドメインのセレンディピティ的発見(具体spec未定)

## 未決定事項

- 採用する具体的なSearXNG MCPサーバー実装(`SecretiveShell/MCP-searxng`が基本形の第一候補、着手時に選定・動作確認する)
- チャットエージェントに常時toolとして持たせるか、必要なドメインだけに持たせるか
- 検索結果をそのままLLMコンテキストに渡すか、件数・文字数を絞る前処理を挟むか

## 依存

- 特になし(SearXNGインスタンスは運用中)
