<!-- /speckit.specify にそのまま渡す下書き。出所: wishlist/spec-kit-handoff.md -->

論文チャットアプリのwalking skeletonを実装する。

やりたいこと:
- チャットでarXivのURLを貼ると、論文のタイトル・著者・abstractだけを取得し、Item + PaperRecordとして最小限保存する(PDF本文抽出・チャンク分割・Embeddingはこの段階では行わない)
- チャットで「今まで保存した論文は?」のように聞くと、保存済みの論文一覧が返る

受け入れ条件:
- FastAPI + pydantic_ai.ag_ui.AGUIAdapter でチャットエンドポイントが立ち上がる
- 最小限のReactチャットUI(@ag-ui/clientのHttpAgentで接続、CopilotKit不使用)からエンドポイントに接続できる
- arXivのURLを貼ってから一覧に反映されるまで一往復で完結する
- 保存先はSQLite(スキーマは後続機能で拡張されることを前提に、Item/PaperRecordの最小フィールドのみ)

やらないこと(このspecの範囲外):
- PDF本文抽出、チャンク分割、Embedding生成(次のspec `002-papers-ingest-full` で扱う)
- 引用関係の取得
- 認証・マルチユーザー対応
