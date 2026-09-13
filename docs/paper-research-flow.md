# 関連論文調査(027)の全体像

ADR-0014の「あるアクションでドメインモデルがどう経由・変化するか」は原則オンデマンド生成・使い捨て(項目3)だが、`docs/chat-agent-flow.md`と同じ理由でこの1本だけ例外的に常設ドキュメント化する: 027は複数ファイル(チャット側のtool・cron駆動のCLI・既存の002/014取り込みパイプライン・複数の新規エージェント)にまたがる非同期バッチ処理で、開発者が現状を把握するまでの負荷が高い。骨格(受付をキューに積むだけにする/CLIバッチが発見→triage→精読→統合を順に行う、という段構成自体)はユーザーストーリー1の実装で固定化されており(`specs/027-related-paper-research/spec.draft.md`参照)、個々のtool一覧のように変更頻度が高いものではない。

完全な鮮度保証は無い手動更新の文書。段構成やファイル配置を変えたら描き直すこと。詳細な仕様・設計判断の理由は`specs/027-related-paper-research/spec.draft.md`が一次情報で、このページは実装済みコードの見取り図に徹する。

## ① 受付(チャットターン、同期)とバッチ実行(cron、非同期)は別プロセス

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Chat as チャットエージェント<br/>(agent/tools/paper_research.py)
    participant Queue as paper_research_records<br/>(status="pending")
    participant Cron as cron
    participant CLI as cli/run_paper_research.py
    participant FE as フロントエンド

    User->>Chat: 「この論文に関連する論文を集めて」
    Chat->>Chat: 起点論文を特定<br/>(論文モード中 or arXiv URL/タイトル指定)
    Chat->>Queue: research_related_papers()<br/>PaperResearchRecord(status="pending")を1件保存
    Chat-->>User: 「キューに追加しました」(即座に返す、調査本体はまだ実行しない)

    Note over Cron,CLI: 数分後(既定 */30 * * * *)
    Cron->>CLI: python -m polaris.cli.run_paper_research
    CLI->>Queue: reclaim_stale() → claim_next_pending()
    CLI->>CLI: run_one_research()(下記②、10〜30分かかる想定)
    CLI->>Queue: mark_done(result_summary) / mark_failed(error)

    FE->>FE: GET /api/paper-research/latest(バナー用)<br/>GET /api/paper-research(一覧モーダル用)
    FE-->>User: バナー→クリックで一覧→クリックで本文(PaperResearchHistoryModal)
```

要点:

- チャット側のtool(`research_related_papers`)は`PaperResearchRecord`を1行作るだけで、発見・精読・統合は一切行わない(`agent/tools/todo.py`の`add_todo`と同じ軽さ)。数分〜数十分かかる処理を同期チャットターンに収めないための設計(`specs/IDEAS.md`)
- 実処理は008/023/024と同じ「OS cron駆動のCLI」パターン(`cli/run_paper_research.py`)。FastAPIサーバーの生存に依存せず、Engine/Repository/Agentを自前で組み立てる
- 完了通知は023と同じ「バナー→クリックで展開」パターンだが、027では「最新1件のバナー→一覧モーダル→詳細」の3段(`PaperResearchBanner.tsx`→`PaperResearchList.tsx`→`PaperResearchHistoryModal.tsx`)。チャット履歴には追加しない

## ② `run_one_research()`の内部(1調査依頼ぶん、`services/paper_research.py`)

```mermaid
flowchart TD
    start["起点論文のarXiv ID"] --> discover

    subgraph discover["発見(paper_research_discovery.py::discover_candidates)"]
        direction TB
        d1["Semantic Scholarでpaper_id解決"] --> d2["references(1hop, backward)"]
        d2 --> d3["citations(1hop, forward)"]
        d3 --> d4["citation_count上位N件のcitations(2hop)"]
        d4 --> d5["タイトル/abstractからキーワード抽出→search"]
        d5 --> d6["paper_idで重複排除、max_candidatesで打ち切り"]
    end

    discover --> triage["粗い判定(agent/paper_triage.py)<br/>triage_batch_size件ずつ、abstractは英語原文のまま<br/>関連ありと判定された候補だけ残す"]

    triage --> select["citation_count降順でmax_deep_read件に絞る"]

    select --> deep_read

    subgraph deep_read["精読(_deep_read_one、候補ごとに逐次)"]
        direction TB
        r1{{"既存Item?<br/>(find_by_arxiv_id)"}}
        r1 -->|Yes| r2{{"PaperDeepAnalysisRecord<br/>キャッシュ済み?"}}
        r1 -->|No| r3{{"arXiv IDまたは<br/>open access PDFあり?"}}
        r2 -->|Yes| reuse["problem/solutionを再利用<br/>(LLM呼び出しなし)"]
        r2 -->|No| extract
        r3 -->|No| abstractOnly["abstractのみで統合段へ<br/>(精読せず「(abstractのみ)」と明示)"]
        r3 -->|Yes| ingest["002/014取り込みパイプライン<br/>(ingest_paper_from_url)"]
        ingest --> discovered["PaperResearchDiscoveredPaper保存<br/>(出自を記録、list_papers等から除外)"]
        discovered --> extract["extract_problem_solution.py<br/>load_full_text()の全文から課題/解決を抽出"]
        extract --> save["PaperDeepAnalysisRecordに保存<br/>(他の調査から再利用可能)"]
    end

    reuse --> outcomes
    save --> outcomes
    abstractOnly --> outcomes["outcomes: (タイトル, 課題, 解決)のリスト"]

    outcomes --> synth

    subgraph synth["統合(agent/research_synthesis.py、アウトライン先行2段階)"]
        direction TB
        s1["Step A: outline()<br/>全論文のタイトル+課題のみ→見出し構成を決める"]
        s2["Step B: synthesize()<br/>アウトライン+全論文(タイトル・課題・解決)を1回で渡す(stuff方式)"]
        s1 --> s2
    end

    synth --> summary["result_summary(統合結果の本文)"]
```

要点:

- 発見・精読は全て**逐次**実行(`asyncio.gather`は使わない)。無料枠LLM/Semantic Scholarの同時実行は非決定的に落ちることが021/027の実機検証で分かっているため
- Semantic Scholarへの全リクエストは`adapters/semantic_scholar/client.py`の`_get_with_retry()`を経由し、指数バックオフ(429/5xx/ネットワークエラーをリトライ、`Retry-After`優先)を必須で掛ける
- embeddingは生成しない(ADR-0011)。精読は全文取り込み(ベクトル検索は使わない)方式
- 統合は当初「refine」方式(1論文ずつ`fold()`)だったが、序盤の論文情報が圧縮で失われる問題があり、2026-09-13にアウトライン先行の2段階に変更した(詳細は`specs/027-related-paper-research/spec.draft.md`「改善: 統合結果が薄い問題」参照)
- 調査で新規に取り込んだ論文(`PaperResearchDiscoveredPaper`)は`list_papers`/論文一覧UI/日次要約から除外される。ユーザーが後から`save_paper`で明示的に保存し直すと出自が外れ、通常のライブラリの一員として扱われる
- 1件の失敗(`run_one_research`の例外)はバッチ全体を止めず`mark_failed`にして次回再試行する(008/023と同じ方針)

## 関連

- 一次情報: `specs/027-related-paper-research/spec.draft.md`(データモデル・設定値・未決定事項の解決経緯まで含む)
- ADR-0011(Ingest時Embedding生成の一時停止、027が全面適用した)、ADR-0014(このドキュメントの位置づけ)
- `docs/chat-agent-flow.md`(チャットエージェント全体の骨格、①の`Chat`部分の詳細)
