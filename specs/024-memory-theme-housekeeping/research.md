# Phase 0 Research: 記憶テーマの定期棚卸し(memory-theme-housekeeping)

`spec.md`のAssumptionsで確定した範囲(v1は検出・表示のみ、実適用は範囲外/週1回想定/localStorage既読管理)
を前提に、`023-daily-summary-notification`(同型の先行実装)と`017-chat-memory`(対象データ)の
実装を直接調べた上で、技術的な未決定事項をここで解消する。

## Decision 1: レイヤー構成は023を1対1で踏襲する

**Decision**: settings → domain entity(SQLModel) → repository → agent(Protocol + Agentラッパー)
→ service(オーケストレーション) → CLI → API(読み取り専用エンドポイント) → frontendバナー、という
`023-daily-summary-notification`のレイヤー構成をそのまま流用する。

**Rationale**: 023は「チャットのターンに紐づかない独立バックグラウンド処理」という、本specと全く同じ
性質の先行実装であり、実機で検証済み。新規パターンを考案するより、確立済みの形をなぞる方がYAGNI
(憲章 原則II)に合う。差分は「対象期間による絞り込みが無い(常に全テーマの現在状態を評価)」
「出力が単一文章ではなく構造化された提案のリスト」の2点のみ。

**Alternatives considered**: 専用のタスクランナー抽象を先に切り出す案は、`spec.draft.md`が
明記する通り「rule of three」判断により却下(025が着手されてから3例揃った時点で判断する)。

## Decision 2: 全テーマの「現在の内容」はファイル(`memory/<slug>.md`)を直接読む、`MemoryTheme.description`では代用しない

**Decision**: 検出処理は`MemoryRepository.list_themes()`でslug一覧と`updated_at`(stale判定用)を取得し、
各slugについて`services/memory.read_theme_file(slug, settings=settings)`で現在状態ファイルの全文を読む。
索引の一行説明(`MemoryTheme.description`)だけでは統合・分割候補の判定はできない。

**Rationale**: `MemoryTheme.description`は想起・抽出LLM呼び出しに渡す軽量な一行説明に過ぎず
(`db/memory_repository.py`のdocstring)、内容の重複や話題の混在を判断するには情報が不足する。
`read_theme_file`は既存関数でありそのまま再利用できる(新規I/O層は不要)。

**Alternatives considered**: `MemoryEvent`ログ全件を直接LLMに渡す案(現在状態ファイルを経由しない)も
検討したが、`019-diary-domain`のDecision 2で確認した通り現在状態ファイルは「ログの読み直し済み
materialized view」であり、こちらの方が短く整理されている。ログ全件を渡すとテーマ数×イベント数で
プロンプトが肥大しやすい(`specs/IDEAS.md`のコンテキスト肥大問題と同じ轍)。

## Decision 3: 検出は1回のLLM呼び出しで全テーマ横断・構造化出力

**Decision**: `agent/memory_extract.py`と同じ「Protocol + Agentラッパー」の形を使うが、
出力は`list[HousekeepingSuggestionItem]`を持つ`BaseModel`(`HousekeepingDetectionResult`)。
全テーマのslug+現在状態ファイル全文を1つのプロンプトにまとめ、LLM呼び出しは1回のみ。

**Rationale**: `023`の日次サマリー生成と同じく「複数の入力を横断して判断する」広いタスクであり、
テーマごとに個別のLLM呼び出しを行うとテーマ数のO(n)倍のレイテンシ・コストになる上、
「テーマAとテーマBが重複している」のような複数テーマにまたがる判断はそもそも1回の呼び出しでないと
下せない。reasoningは`023`と同じ理由で無効化しない(狭いスキーマ埋めではなく、複数テーマを横断した
判断が要るため、`_MEMORY_MODEL_SETTINGS`のようなreasoning無効化は適用しない)。

**Alternatives considered**: 埋め込みベクトルによる類似度計算を前段に挟み、LLMには類似候補ペアだけを
渡す案は、`spec.md`のAssumptionsで明記した通りテーマ数が少ない現状では投資対効果が薄く却下。
テーマごとに個別のtool呼び出し(`@agent.tool`)にする案も検討したが、`agent/tools/memory.py`の
docstringが明記する通り「メインのチャットエージェントに記憶系toolを持たせない」設計方針と対称的に、
本バッチも独立した1回のAgent実行で完結させる方がシンプル(チャットエージェントとは別のAgentインスタンス)。

## Decision 4: モデル選択は`settings.llm.model_id`(メインモデル)

**Decision**: 検出用エージェントは017の想起用軽量モデル(`settings.memory.recall_model_id`、qwen3-8b)
ではなく、メインのチャットモデル(`settings.llm.model_id`)を使う。

**Rationale**: `023`の日次サマリーが「複数ドメインを横断して要約する」ことを理由にメインモデルを
選んだのと同じ判断軸。テーマ間の重複・分割の判断は017の想起(短い発言をテーマ索引と照合するだけの
単純な分類タスク)より複雑な推論を要する。

**Alternatives considered**: 専用の`housekeeping_model_id`設定を新設する案も検討したが、
現時点でメインモデルと差別化する具体的理由が無く、憲章 原則II(YAGNI)によりv1では見送る。
将来必要になれば`DailySummarySettings`のように専用設定を切り出せる余地は残す。

## Decision 5: データモデルは「バッチ全体を1単位として全置き換え」、per-suggestion永続dismissは持たない

**Decision**: `MemoryHousekeepingSuggestion`テーブルは1提案=1行だが、バッチ実行のたびに
既存の全行を削除してから新しい行を挿入する(`replace_all`)。全行が同じ`generated_at`(バッチ実行時刻)
を共有し、フロントの既読判定はこの`generated_at`を023の`summary_date`と同じ役割で使う。

**Rationale**: `spec.md`のFR-005/FR-006(「毎回のバッチ実行で完全に置き換え」「0件ならクリア」)を
素直に満たす最もシンプルな実装。`spec.draft.md`のたたき台にあった`dismissed: bool`カラムは、
`spec.md`のAssumptionsで確定した通り既読管理をlocalStorage側に寄せたため不要(023の
`DailySummaryRecord`にも`read_at`が無いのと同じ判断)。

**Alternatives considered**: バッチ全体を1行のJSON文字列カラムに詰める案(`DailySummaryRecord.content`
と同型)も検討したが、「種別・対象テーマ・理由」という構造化されたフィールド(FR-003)を
API/フロント側でそのまま構造化データとして扱いたい(023の`content`は自由文だが、本specは種別ごとの
表示分けが要る)ため、1提案=1行のテーブルの方が素直。SQLiteでの削除+挿入は小規模データ量
(テーマ十数件、提案は多くてもテーマ数と同程度)では性能上の懸念にならない。

## Decision 6: CLIは対象期間パラメータを持たない

**Decision**: `cli/run_memory_housekeeping.py`は`--date`のような対象期間引数を持たない
(常に「実行時点の全テーマの現在状態」を評価する)。

**Rationale**: `023`が「対象日」を引数に取るのは集計対象期間(その日の活動)を絞り込む必要が
あるため。本specは期間を絞らず全テーマを毎回評価するので、対応する引数が存在しない
(spec Assumptions: 「頻度はcrontab側の設定のみで表現でき、コード側に頻度用の設定値は不要」)。

**Alternatives considered**: なし(023の引数をそのまま真似る理由が無いことを確認しただけ)。
