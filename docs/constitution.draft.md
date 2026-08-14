<!-- /speckit.constitution にそのまま渡す下書き。出所: wishlist/spec-kit-handoff.md -->

このプロジェクトは個人用の知識・生活管理プラットフォーム。以下を原則とする。

- 実装言語はPython、型付けはPydantic中心。Pydantic AI v2をエージェント実装に使う。
- 個人利用が前提。過度な汎用化・DIフレームワーク導入は避け、YAGNIを徹底する。
- モデルは開発フェーズでOpenRouter経由のQwen3-30B-A3B(無料)、本番フェーズでQwen3.6-35B-A3Bを使う。モデル選択は設定値の切替のみで行い、コードに埋め込まない。
- 知識データはHub/Satelliteパターンで管理する。汎用のItem/Chunk/Embeddingと、ドメイン固有のsatelliteテーブル(例: PaperRecord)を分離する。
- チャットUIはAG-UIプロトコルに乗せる。pydantic_ai.ag_ui.AGUIAdapterをFastAPIのエンドポイントに繋ぎ、フロントエンドは@ag-ui/clientのHttpAgentで直接接続する。CopilotKit/Next.jsは使わない。
- v1はlocalhost・単一ユーザー・認証なしのスコープとする。
- 機能追加はwalking skeleton(全レイヤーを貫く最小の一本を先に通してから深掘りする)の考え方で進める。
