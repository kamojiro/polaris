# Specs 一覧・進捗状況

feature単体のspecファイルには書きにくい「spec間の順序・着手可否」をここで管理する。ステータスが変わったら都度更新する。

specにするほど固まっていない思いつきは[IDEAS.md](IDEAS.md)にメモする。

## 実装順

`#`(採番順)とは別に、実際に着手する順番はこちら。フェーズ内は上から順に、依存関係も考慮済み。003・007・014・015・017・018は完了済みのため対象外(003/015の追加提案3件も2026-08-26に実装完了)。008もPhase Aが完了済み(Phase Bのみ009待ちで残る)。

1. **013 (ir-analysis-domain)** — 依存なし、spec詳細化済みで着手可能
2. **023 (daily-summary-notification)** — 依存なし(002/007/013/017の既存ドメインだけで動く設計)、spec詳細化済みで着手可能。013と並行でも順不同でもよい
3. 024 (memory-theme-housekeeping) — 詳細化未着手・優先度も未定。023のパターンを再利用する着想メモ
4. 025 (ir-tracking-expansion) — 詳細化未着手・優先度も未定。013への追加。Stage 1(既存追跡企業の新規開示チェック)は詳細化済み
5. ~~004 (citation-relations)~~ — 見送り
6. ~~005 (eval-harness)~~ — いつかやるリストへ(下記参照)
7. 006 (chatlog-backfill) — 005に依存するため005が動くまで自動的に後回し
8. 016 (paper-structured-parsing) — 015を使ってみて図表QA・引用根拠が必要になったら着手(スケルトンのみ、着手トリガー待ち)
9. 009 (dashboard) — 008 Phase B・010の依存元
10. 010 (mobile-pwa) — 009に依存
11. 011 (agent-registry)
12. 012 (local-llm-cutover)
13. 019 (diary-domain) — 詳細化未着手・優先度も未定。着想メモのみ
14. 020 (google-workspace-integration) — 詳細化未着手・優先度も未定。着想メモのみ
15. 021 (discord-integration) — 詳細化未着手・優先度も未定。着想メモのみ
16. 022 (misskey-integration) — 詳細化未着手・優先度も未定。着想メモのみ(投稿は許可制の方針のみ決定済み)

## いつかやるリスト

spec自体は書けていて実装開始可能だが、直近では優先度を下げて着手しないもの。

- 005 (eval-harness): 設計は完了しているが、直近で計測してもデータ量的に旨みが薄いため後回し。着手する気になったらステータスを✅に戻す

| # | spec | フェーズ | ステータス | 備考 |
|---|---|---|---|---|
| 001 | [walking-skeleton](001-walking-skeleton/spec.draft.md) | 1 | ✔️ 完了 | AG-UI+FastAPI+pydantic-ai+Reactの一往復が動作確認済み |
| 002 | [papers-ingest-full](002-papers-ingest-full/spec.draft.md) | 1 | ✔️ 完了 | arXiv入力を実装(local_pdf/URLは014で追加)。PDF取得→pypdf抽出→Structureエージェント→チャンク分割→Qwen3-Embedding-0.6B→SQLite(vec0)まで動作確認済み。**2026-08-26追記**: 生成したembeddingを読み出す機能が1つも無いと判明し、ADR-0004でIngest時のembedding生成を一時停止(`Chunk`テーブル・コードは残す) |
| 003 | [chat-ui-polish](003-chat-ui-polish/spec.draft.md) | 1 | ✔️ 完了 | react-markdown導入・list_papersのgenerative UI化(専用テーブル)・レイアウト調整を実装済み。追加提案(2026-08-23、2026-08-26実装): メッセージのコピーボタン、入力欄の「論文一覧」クイックアクションボタン |
| 004 | [citation-relations](004-citation-relations/spec.draft.md) | 1 | 🚫 やらない | 見送り決定。設計(スタブは作らない方針)は記録として残す |
| 005 | [eval-harness](005-eval-harness/spec.draft.md) | 1 | 🗓 いつか | spec自体は完成済み(対象を002のStructure抽出と001/003のtool呼び出しの実データに絞って具体化)。直近では実装しない、いつかやるリスト行き |
| 006 | [chatlog-backfill](006-chatlog-backfill/spec.draft.md) | 1 | 💤 スケルトンのみ | 005の後。Eval harnessの検証データとしても使う |
| 007 | [todo-domain](007-todo-domain/spec.draft.md) | 2 | ✔️ 完了 | v1はCRUD+3バケット(day/month/life)分類のみ。新規エージェント/レジストリは作らず既存の単一チャットエージェントにtool追加。バケット分類はLLMがadd_todoのscale引数を自然文から直接選ぶ。優先度は最終更新日からの経過時間(熟成度)のみ、Interest依存は008以降に持ち越し。リマインド・現況調査エージェントは対象外(将来spec) |
| 008 | [daily-digest-domain](008-daily-digest-domain/spec.draft.md) | 2 | ⏸ 待機中(Phase Aは✔️完了) | エコーチェンバー可視化。対立軸は静的ソースラベル方式(LLM自動スタンス推定はしない)、4分類はv1固定。Phase A(Ingest/Structure)実装済み: `feedparser`でRSS/Atom取得、`agent/structure_news.py`で要約生成、`cli/ingest_news.py`をOS cronから1日1回叩く方式、`list_news`ツール+`NewsList.tsx`で一覧表示。Phase B(Relate/Surface、関係グラフ表示)は`009-dashboard`待ち。`Relation`/`Event`テーブルは未実装、`Interest`はv1で作らない |
| 009 | [dashboard](009-dashboard/spec.draft.md) | 3 | 💤 スケルトンのみ | 複数ドメインが揃ってから。003のgenerative UIの限界がトリガー |
| 010 | [mobile-pwa](010-mobile-pwa/spec.draft.md) | 3 | 💤 スケルトンのみ | 009である程度画面が固まってから |
| 011 | [agent-registry](011-agent-registry/spec.draft.md) | 4 | 💤 スケルトンのみ | 複数ドメインのエージェントが実在する状態で強化 |
| 012 | [local-llm-cutover](012-local-llm-cutover/spec.draft.md) | 4 | 💤 スケルトンのみ | Layer0のモデル抽象を活かす想定。005の実績があると判断しやすい |
| 013 | [ir-analysis-domain](013-ir-analysis-domain/spec.draft.md) | 5 | ✅ 実装開始可能 | EDINET API v2(無料、要APIキー)の書類取得(`type=2`)はPDFをそのまま返すため、015と同じPDF→pypdf→全文チャット方式を流用する。企業名検索はAPI側に無いためv1はdocID直接入力のみ。ニュース関連付け・SEC EDGAR・XBRL構造化解析は範囲外 |
| 014 | [paper-url-pdf-ingest](014-paper-url-pdf-ingest/spec.draft.md) | 1 | ✔️ 完了 | 002で当初スコープから外したurl/local_pdf対応。URL直リンクは`adapters/pdf/downloader.py`でダウンロード、local_pdfは`POST /api/papers/upload`+`save_paper`ツール経由(ADR-0002、AG-UI添付は不採用)。非arXivのメタデータは`agent/extract_metadata.py`で本文冒頭から抽出、重複判定は`source_url`を流用 |
| 015 | [paper-qa-chat](015-paper-qa-chat/spec.draft.md) | 1 | ✔️ 完了 | 1論文とのチャットはベクトル検索を使わず、`PaperRecord.pdf_path`から都度pypdf再抽出した全文を`get_paper_full_text`ツールでコンテキストに渡す方式。Chunk/Embeddingはライブラリ横断検索用として役割を分ける。prompt cachingは実測(かつコード上も`qwen`系はno-opと確認)したがv1では見送り。代わりにトークン使用量・コストをAG-UIのCUSTOMイベント経由でチャットUIに表示し、キャッシュのヒット状況を毎ターン目視できるようにした。追加提案(2026-08-23、2026-08-26実装): 論文モードへの手動エントリー(`PaperList`からのクリック) |
| 016 | [paper-structured-parsing](016-paper-structured-parsing/spec.draft.md) | 1 | 💤 スケルトンのみ(着手トリガー待ち) | 015を使ってみて図表QA・引用根拠が本当に必要になったら着手。GROBID/Docling等でのセクション構造化、citation grounding |
| 017 | [chat-memory](017-chat-memory/spec.draft.md) | - | ✔️ 完了 | チャットからテーマ別に長期記憶を抽出・蓄積する。ログ層(`MemoryEvent`、追記のみ)+現在状態層(`memory/<slug>.md`、書き直し)の二層構造。ADR-0003の3段パイプライン(前処理=想起/メイン/後処理=抽出)を`/api/chat`に実装、`agent.deps_type`を自前の`ChatDeps`(dataclass)に差し替えて論文モードのstateと分離した。テーマ統合・分割・改名(明示指示での見直し)はv1未実装 |
| 018 | [web-search-tool](018-web-search-tool/spec.draft.md) | - | ✔️ 完了 | 自前ホスト済みのSearXNGに`adapters/searxng/client.py`から直接HTTPで問い合わせる自前adapter方式(MCPは見送り、詳細はspec参照)。`web_search`ツールを常時登録。007/013/017など複数specから使われる横断インフラ |
| 019 | [diary-domain](019-diary-domain/spec.draft.md) | - | 💤 スケルトンのみ | チャットで会話すると日記がつけられる。017と同じログ層+現在状態層の仕組みをキーが「テーマ」ではなく「日付」の場合として再利用できそうという着想。保存先ディレクトリは`memory/`と分けて`diary/`にする。入力欄のモードチップUI(paper/diary併存、日記はセッション単位トグル)はモックアップで確認済み |
| 020 | [google-workspace-integration](020-google-workspace-integration/spec.draft.md) | - | 💤 スケルトンのみ | Google Calendar/Driveとの連携。用途未確定(Calendarは007のリマインド、Driveは文書取り込み元/バックアップ先候補)。公式MCP(Calendar)とコミュニティMCP(Drive候補)が混在しうる |
| 021 | [discord-integration](021-discord-integration/spec.draft.md) | - | 💤 スケルトンのみ | Discord連携。通知先として使うか、代替フロントエンドとして使うか未確定 |
| 022 | [misskey-integration](022-misskey-integration/spec.draft.md) | - | 💤 スケルトンのみ | Misskey連携。読み取りは自動、**投稿は許可制**にする方針のみ決定済み。elicitationまたは二段階tool構成で実現する想定 |
| 023 | [daily-summary-notification](023-daily-summary-notification/spec.draft.md) | - | ✅ 実装開始可能 | 1日の活動を横断要約し、フロントに通知的に表示する。チャットターンに紐づかない初めての処理で、ADR-0003のパイプラインには含めず`cron`ベースのバッチとして実装。002/007/013/017の既存ドメインだけで動く設計、008/019は実装され次第集計対象に追加 |
| 024 | [memory-theme-housekeeping](024-memory-theme-housekeeping/spec.draft.md) | - | 💤 スケルトンのみ | 017のテーマ整理を023と同じcron駆動で定期実行し、統合・分割・stale検出を「提案」として出す(自動適用はしない)。「現状調査・再現性テスト」は着想止まりでv1範囲外 |
| 025 | [ir-tracking-expansion](025-ir-tracking-expansion/spec.draft.md) | - | 💤 スケルトンのみ | 013に追跡機能を追加。Stage 1(既存追跡企業の新規開示を日次チェック、詳細化済み)→Stage 2(追跡対象企業自体の発見、将来)の段階的拡大設計 |

## ステータスの意味

- 💤 スケルトンのみ: ディレクトリと概要はあるが、詳細(受け入れ条件・データモデル等)はまだ詰めていない
- ⏸ 待機中: 依存するspecや未決定事項がある。理由を備考に書く
- ✅ 実装開始可能: 依存・未決定事項なし。`/speckit.specify`等に渡してすぐ着手できる
- 🚧 実装中
- ✔️ 完了
- 🚫 やらない: 検討した上で見送り。設計や判断の経緯は記録として残す
- 🗓 いつか: spec自体は実装開始可能な状態まで詰めてあるが、優先度を下げて直近では着手しない

スケルトンのspecを実際に着手するときは、`spec.draft.md`を書き足してから(必要ならADRも書いてから)ステータスを✅に上げる。
