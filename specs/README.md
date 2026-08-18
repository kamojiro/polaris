# Specs 一覧・進捗状況

feature単体のspecファイルには書きにくい「spec間の順序・着手可否」をここで管理する。ステータスが変わったら都度更新する。

## 実装順

`#`(採番順)とは別に、実際に着手する順番はこちら。フェーズ内は上から順に、依存関係も考慮済み。003は実装着手済みのため対象外。

1. 014 (paper-url-pdf-ingest) — 002の後回し分、最優先で片付ける
2. 004 (citation-relations)
3. 005 (eval-harness)
4. 006 (chatlog-backfill) — 005に依存
5. 007 (todo-domain)
6. 008 (daily-digest-domain)
7. 009 (dashboard)
8. 010 (mobile-pwa) — 009に依存
9. 011 (agent-registry)
10. 012 (local-llm-cutover)
11. 013 (ir-analysis-domain)

| # | spec | フェーズ | ステータス | 備考 |
|---|---|---|---|---|
| 001 | [walking-skeleton](001-walking-skeleton/spec.draft.md) | 1 | ✔️ 完了 | AG-UI+FastAPI+pydantic-ai+Reactの一往復が動作確認済み |
| 002 | [papers-ingest-full](002-papers-ingest-full/spec.draft.md) | 1 | ✔️ 完了 | arXiv入力のみ実装(local_pdf/URLは範囲外、InputKind判定のみ将来拡張可能な形で用意)。PDF取得→pypdf抽出→Structureエージェント→チャンク分割→Qwen3-Embedding-0.6B→SQLite(vec0)まで動作確認済み |
| 003 | [chat-ui-polish](003-chat-ui-polish/spec.draft.md) | 1 | 🚧 実装中 | react-markdown導入・list_papersのgenerative UI化(専用テーブル)・レイアウト調整を実装済み。TOOL_CALL_RESULTへのJSON配線とLLMの一言応答は実リクエストで動作確認済み。ブラウザでの見た目の最終確認待ち |
| 004 | [citation-relations](004-citation-relations/spec.draft.md) | 1 | ✅ 実装開始可能 | ライブラリ内の論文同士のみ`cites`のRelationを作る方針(スタブは作らない)。未取り込み分は集計カウントのみ保持 |
| 005 | [eval-harness](005-eval-harness/spec.draft.md) | 1 | ✅ 実装開始可能 | 対象を002のStructure抽出と001/003のtool呼び出しの実データに絞って具体化した |
| 006 | [chatlog-backfill](006-chatlog-backfill/spec.draft.md) | 1 | 💤 スケルトンのみ | 005の後。Eval harnessの検証データとしても使う |
| 007 | [todo-domain](007-todo-domain/spec.draft.md) | 2 | 💤 スケルトンのみ | 論文ドメインのパターンを横展開 |
| 008 | [daily-digest-domain](008-daily-digest-domain/spec.draft.md) | 2 | 💤 スケルトンのみ | エコーチェンバー可視化。セレンディピティ機能の再検討を含む |
| 009 | [dashboard](009-dashboard/spec.draft.md) | 3 | 💤 スケルトンのみ | 複数ドメインが揃ってから。003のgenerative UIの限界がトリガー |
| 010 | [mobile-pwa](010-mobile-pwa/spec.draft.md) | 3 | 💤 スケルトンのみ | 009である程度画面が固まってから |
| 011 | [agent-registry](011-agent-registry/spec.draft.md) | 4 | 💤 スケルトンのみ | 複数ドメインのエージェントが実在する状態で強化 |
| 012 | [local-llm-cutover](012-local-llm-cutover/spec.draft.md) | 4 | 💤 スケルトンのみ | Layer0のモデル抽象を活かす想定。005の実績があると判断しやすい |
| 013 | [ir-analysis-domain](013-ir-analysis-domain/spec.draft.md) | 5 | 💤 スケルトンのみ | データソースの契約・コストが絡むため優先度最低 |
| 014 | [paper-url-pdf-ingest](014-paper-url-pdf-ingest/spec.draft.md) | 1 | ✅ 実装開始可能 | 002で当初スコープから外したurl/local_pdf対応。URL直リンクは単純ダウンロード、local_pdfはチャット添付(AG-UI)を第一候補、ダメならアップロード専用エンドポイントにフォールバック |

## ステータスの意味

- 💤 スケルトンのみ: ディレクトリと概要はあるが、詳細(受け入れ条件・データモデル等)はまだ詰めていない
- ⏸ 待機中: 依存するspecや未決定事項がある。理由を備考に書く
- ✅ 実装開始可能: 依存・未決定事項なし。`/speckit.specify`等に渡してすぐ着手できる
- 🚧 実装中
- ✔️ 完了

スケルトンのspecを実際に着手するときは、`spec.draft.md`を書き足してから(必要ならADRも書いてから)ステータスを✅に上げる。
