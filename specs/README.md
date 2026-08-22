# Specs 一覧・進捗状況

feature単体のspecファイルには書きにくい「spec間の順序・着手可否」をここで管理する。ステータスが変わったら都度更新する。

specにするほど固まっていない思いつきは[IDEAS.md](IDEAS.md)にメモする。

## 実装順

`#`(採番順)とは別に、実際に着手する順番はこちら。フェーズ内は上から順に、依存関係も考慮済み。003・007・014・015は完了済みのため対象外。

1. ~~004 (citation-relations)~~ — 見送り
2. ~~005 (eval-harness)~~ — いつかやるリストへ(下記参照)
3. 006 (chatlog-backfill) — 005に依存するため005が動くまで自動的に後回し
4. 016 (paper-structured-parsing) — 015を使ってみて図表QA・引用根拠が必要になったら着手(スケルトンのみ、着手トリガー待ち)
5. 008 (daily-digest-domain)
6. 009 (dashboard)
7. 010 (mobile-pwa) — 009に依存
8. 011 (agent-registry)
9. 012 (local-llm-cutover)
10. 013 (ir-analysis-domain)

## いつかやるリスト

spec自体は書けていて実装開始可能だが、直近では優先度を下げて着手しないもの。

- 005 (eval-harness): 設計は完了しているが、直近で計測してもデータ量的に旨みが薄いため後回し。着手する気になったらステータスを✅に戻す

| # | spec | フェーズ | ステータス | 備考 |
|---|---|---|---|---|
| 001 | [walking-skeleton](001-walking-skeleton/spec.draft.md) | 1 | ✔️ 完了 | AG-UI+FastAPI+pydantic-ai+Reactの一往復が動作確認済み |
| 002 | [papers-ingest-full](002-papers-ingest-full/spec.draft.md) | 1 | ✔️ 完了 | arXiv入力を実装(local_pdf/URLは014で追加)。PDF取得→pypdf抽出→Structureエージェント→チャンク分割→Qwen3-Embedding-0.6B→SQLite(vec0)まで動作確認済み |
| 003 | [chat-ui-polish](003-chat-ui-polish/spec.draft.md) | 1 | ✔️ 完了 | react-markdown導入・list_papersのgenerative UI化(専用テーブル)・レイアウト調整を実装。ブラウザでの見た目の最終確認済み |
| 004 | [citation-relations](004-citation-relations/spec.draft.md) | 1 | 🚫 やらない | 見送り決定。設計(スタブは作らない方針)は記録として残す |
| 005 | [eval-harness](005-eval-harness/spec.draft.md) | 1 | 🗓 いつか | spec自体は完成済み(対象を002のStructure抽出と001/003のtool呼び出しの実データに絞って具体化)。直近では実装しない、いつかやるリスト行き |
| 006 | [chatlog-backfill](006-chatlog-backfill/spec.draft.md) | 1 | 💤 スケルトンのみ | 005の後。Eval harnessの検証データとしても使う |
| 007 | [todo-domain](007-todo-domain/spec.draft.md) | 2 | ✔️ 完了 | v1はCRUD+3バケット(day/month/life)分類のみ。新規エージェント/レジストリは作らず既存の単一チャットエージェントにtool追加。バケット分類はLLMがadd_todoのscale引数を自然文から直接選ぶ。優先度は最終更新日からの経過時間(熟成度)のみ、Interest依存は008以降に持ち越し。リマインド・現況調査エージェントは対象外(将来spec) |
| 008 | [daily-digest-domain](008-daily-digest-domain/spec.draft.md) | 2 | 💤 スケルトンのみ | エコーチェンバー可視化。セレンディピティ機能の再検討を含む |
| 009 | [dashboard](009-dashboard/spec.draft.md) | 3 | 💤 スケルトンのみ | 複数ドメインが揃ってから。003のgenerative UIの限界がトリガー |
| 010 | [mobile-pwa](010-mobile-pwa/spec.draft.md) | 3 | 💤 スケルトンのみ | 009である程度画面が固まってから |
| 011 | [agent-registry](011-agent-registry/spec.draft.md) | 4 | 💤 スケルトンのみ | 複数ドメインのエージェントが実在する状態で強化 |
| 012 | [local-llm-cutover](012-local-llm-cutover/spec.draft.md) | 4 | 💤 スケルトンのみ | Layer0のモデル抽象を活かす想定。005の実績があると判断しやすい |
| 013 | [ir-analysis-domain](013-ir-analysis-domain/spec.draft.md) | 5 | 💤 スケルトンのみ | データソースの契約・コストが絡むため優先度最低 |
| 014 | [paper-url-pdf-ingest](014-paper-url-pdf-ingest/spec.draft.md) | 1 | ✔️ 完了 | 002で当初スコープから外したurl/local_pdf対応。URL直リンクは`adapters/pdf/downloader.py`でダウンロード、local_pdfは`POST /api/papers/upload`+`save_paper`ツール経由(ADR-0002、AG-UI添付は不採用)。非arXivのメタデータは`agent/extract_metadata.py`で本文冒頭から抽出、重複判定は`source_url`を流用 |
| 015 | [paper-qa-chat](015-paper-qa-chat/spec.draft.md) | 1 | ✔️ 完了 | 1論文とのチャットはベクトル検索を使わず、`PaperRecord.pdf_path`から都度pypdf再抽出した全文を`get_paper_full_text`ツールでコンテキストに渡す方式。Chunk/Embeddingはライブラリ横断検索用として役割を分ける。prompt cachingは実測(かつコード上も`qwen`系はno-opと確認)したがv1では見送り。代わりにトークン使用量・コストをAG-UIのCUSTOMイベント経由でチャットUIに表示し、キャッシュのヒット状況を毎ターン目視できるようにした |
| 016 | [paper-structured-parsing](016-paper-structured-parsing/spec.draft.md) | 1 | 💤 スケルトンのみ(着手トリガー待ち) | 015を使ってみて図表QA・引用根拠が本当に必要になったら着手。GROBID/Docling等でのセクション構造化、citation grounding |

## ステータスの意味

- 💤 スケルトンのみ: ディレクトリと概要はあるが、詳細(受け入れ条件・データモデル等)はまだ詰めていない
- ⏸ 待機中: 依存するspecや未決定事項がある。理由を備考に書く
- ✅ 実装開始可能: 依存・未決定事項なし。`/speckit.specify`等に渡してすぐ着手できる
- 🚧 実装中
- ✔️ 完了
- 🚫 やらない: 検討した上で見送り。設計や判断の経緯は記録として残す
- 🗓 いつか: spec自体は実装開始可能な状態まで詰めてあるが、優先度を下げて直近では着手しない

スケルトンのspecを実際に着手するときは、`spec.draft.md`を書き足してから(必要ならADRも書いてから)ステータスを✅に上げる。
