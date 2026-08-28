# ADR (Architecture Decision Records)

後戻りしにくい・理由を残しておきたい決定をここに1件ずつ記録する(Nygard/MADR形式: Context / Decision / Consequences)。specは「何を作るか」、ADRは「なぜその選択をしたか」を担当する。

- [0001. ストレージにSQLiteを採用する](0001-storage-sqlite.md)
- [0002. ローカルPDFの取り込みは専用アップロードエンドポイントで行う](0002-local-pdf-upload-endpoint.md)
- [0003. チャットターンを前処理/メイン/後処理の3段パイプラインとして構造化する](0003-chat-turn-pipeline.md)
- [0004. Hub/Satelliteパターンでデータをモデリングする](0004-hub-satellite-pattern.md)
- [0005. AG-UIプロトコル + @ag-ui/client直接接続を採用する](0005-ag-ui-direct-connection.md)
- [0006. OpenRouter経由のモデル抽象を採用する](0006-openrouter-model-abstraction.md)
- [0007. GitHub Spec Kitを採用する](0007-github-spec-kit.md)
- [0008. MCP経由か自前adapterかは、API複雑さと信頼できる実装の有無で判断する](0008-mcp-vs-custom-adapter.md)
- [0009. 単一文書QAは全文インコンテキスト方式を採用する](0009-single-document-qa-full-context.md)
- [0010. 長期記憶をログ層+現在状態層の二層構造で管理する](0010-memory-log-and-current-state-layers.md)

`0000-template.md` をコピーし、次は `0011-...md` から番号を振って書き起こす。
