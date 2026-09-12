# 027. 関連論文調査(引用チェイニング)

## ステータス

💤 スケルトンのみ(2026-09-12、`specs/IDEAS.md`の「調査メモ: テーマ別の論文調査・要約」から着想。まずユーザーストーリー1のみ実装対象として詳細化)

## 概要

「論文Aに関連する論文を集めてまとめてください」を実現する。論文Aを起点に引用チェイニング(citation chaining/スノーボール法)で関連論文を集め、各論文から「課題」「解決済み」を抽出し、テーマ全体の理解として統合する。

`IDEAS.md`に記録した4つのユーザーストーリーのうち、今回はストーリー1のみをスコープにする(ストーリー2の「継続調査」・ストーリー3の時系列統合・ストーリー4の再帰的サブテーマ分解は将来spec)。

## 全体方針(IDEAS.mdからの引き継ぎ)

- 発見: 引用チェイニング(Semantic Scholar Academic Graph API、無料・キー不要)
- 分析: 関連ありと判定された論文のみ精読(既存の002/014取り込みパイプラインを利用)
- 統合: coarse-to-fine(粗い判定→精読)。ベクトル検索/embeddingは使わない(ADR-0011のまま)
- 実行方式: 同期tool呼び出しにせず、キュー+バッチ処理(非同期)。完了通知は023のバナーパターン

## 処理フロー(ユーザーストーリー1)

### 1. 受付

チャットの`research_related_papers`tool(`agent/tools/paper_research.py`のような新規ファイル、ADR-0013のドメイン分割に倣う)で、`PaperResearchRecord(seed_item_id=..., status="pending")`を1行作るだけ。実処理はしない(`add_todo`程度の軽さ)。

論文Aの指定方法は2通り用意する:

- 論文モード中(`active_paper`が設定されている状態)なら、`get_paper_full_text`と同じく`RunContext[ChatDeps]`経由で`ctx.deps.state.active_paper.item_id`を読む(LLMは引数を渡さない)
- 論文モード外から呼ぶ場合は`save_paper`の`url`引数と同様、明示的に`arxiv_id`かURLを渡す形も用意する

### 2. 発見(cron/CLI側で実行)

論文Aの`arXiv ID`から`GET /graph/v1/paper/arXiv:{id}`でSemantic ScholarのpaperIdを解決する(既存の`PaperRecord`にはarXiv IDのみで、Semantic Scholar側のID解決ステップが必要)。

- **backward(1hop)**: `GET /graph/v1/paper/{paperId}/references` — Aの参考文献
- **forward(1hop)**: `GET /graph/v1/paper/{paperId}/citations` — Aを引用してる論文
- **2hop**: 1hopで見つかった論文(B)それぞれについて、Bのcitationsも取得。組み合わせ爆発を避けるため、Bは引用数上位N件(例: 5件)に絞り、各Bのcitationsも上位M件(例: 10件)に絞る
- **キーワード検索**: Aのタイトル・abstractから軽量LLM呼び出しでキーワードを2〜3個抽出し、`GET /graph/v1/paper/search?query=...`で検索

集めた候補をpaperIdで重複排除し、候補プールとして保存する(合計30〜50件程度を想定、Semantic Scholarの無料枠は100 req/5分なのでこの規模なら余裕がある)。

### 3. 粗い判定(triage)

候補プールを10件ずつバッチにし、各論文のabstract(**原文の英語のまま**LLMに渡す。日本語訳はしない。LLMの学習データは技術文書だと英語が厚く、翻訳を挟むより原文を直接読ませた方が精度が高い。翻訳が要るのは人間に見せる表示層のみ)を見せて「論文Aのテーマに関連し、精読する価値があるか」を判定する。関連ありと判定された論文だけ次段に進む。

### 4. 精読+キャッシュ

関連ありと判定された論文について:

- 既にPolarisのライブラリに取り込み済み(`PaperRecord`が存在)ならそれを使う
- 未取り込みならarXiv IDが分かる範囲で002/014の取り込みパイプラインに乗せる(Semantic Scholar以外のソース論文でarXiv IDが無い場合の扱いは未決定、下記参照)
- 全文から「課題(この論文が取り組んでいる未解決の問題)」「解決済み(この論文が示した解決・知見)」を抽出する新規プロンプトを用意する(既存の`extract_metadata.py`の要約とは別軸の抽出)
- 結果を新規`PaperDeepAnalysisRecord`(item_id紐づけ、Hub/Satellite)に保存し、他の調査から再利用できるようにする

### 5. 統合

精読結果を順番に見ていき、「テーマの課題」「解決済みのこと」を逐次合成する。017の`AgentMemoryRewriter.rewrite()`と同型のパターンだが、指示文は「課題/解決」の軸でまとめるよう専用化する。

### 6. 完了通知

`023-daily-summary-notification`と同じバナー→クリックで展開のUIパターンで、統合結果を提示する。

## データモデル(たたき台)

```python
class PaperResearchRecord(SQLModel, table=True):
    __tablename__ = "paper_research_records"

    id: str = Field(primary_key=True)
    seed_item_id: str = Field(foreign_key="items.id", index=True)
    status: str  # "pending" | "in_progress" | "done" | "failed"
    result_summary: str | None = None  # 統合結果(課題/解決済み)
    created_at: datetime
    completed_at: datetime | None = None


class PaperDeepAnalysisRecord(SQLModel, table=True):
    __tablename__ = "paper_deep_analysis_records"

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True, unique=True)
    problem: str    # この論文が取り組む課題
    solution: str   # この論文が示した解決・知見
    created_at: datetime
```

## 未決定事項(2026-09-12実装完了時点で解決)

- ~~2hop・キーワード検索の絞り込みパラメータ~~ → `settings.paper_research.*`(`references_limit`/`citations_limit`/`hop2_seed_count`/`hop2_citations_limit`/`search_limit`/`max_candidates`)として全て設定値に出した。既定値のままだが実機でチューニング可能
- ~~Semantic Scholar上にしか無くarXiv IDが取れない論文の全文取得手段~~ → `openAccessPdf.url`が空文字列でなければ014のURL取り込み経路に渡す。どちらも無い場合は取り込まず、abstractのみで統合段に持ち込む(`services/paper_research.py::_deep_read_one`)
- `research_arxiv(query)`(IDEAS.mdの旧候補)との役割分担は未着手のまま(将来spec)
- ~~cron実行の頻度・1回あたりの消化件数~~ → `settings.paper_research.max_records_per_run`(既定1件)。頻度はcrontab側の設定のみで表現し、コード側に頻度用の設定値は持たない(023/024と同じ判断)。推奨は`*/30 * * * *`(`cli/run_paper_research.py`のdocstring参照)

## 実装状況

✔️ ユーザーストーリー1、実装完了(2026-09-12)。Semantic ScholarのAPIキーは必須(無認証は実測で不安定、`docs/adr`は無いがコード内コメントに実測値を記録)。ADR-0011(Ingest時Embedding生成の一時停止)をこの作業で初めてコードへ全面適用した。調査で自動取り込みされた論文は`PaperResearchDiscoveredPaper`で出自を持ち、`list_papers`等のライブラリ表示からは除外される(2026-09-12にユーザー確認、spec本文には記載が無かった追加要件)。ストーリー2〜4は引き続き未着手。

## 依存

- `002-papers-ingest-full`/`014-paper-url-pdf-ingest`(論文取り込みパイプライン)
- `008-daily-digest-domain`(cron+CLIのバッチ実行パターン、通知バナーのUI)
- `017-chat-memory`(`rewrite()`の逐次合成パターン)
- `specs/IDEAS.md`「調査メモ: テーマ別の論文調査・要約」(全体設計の背景)
