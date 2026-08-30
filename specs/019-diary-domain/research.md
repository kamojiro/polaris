# Phase 0 Research: 日記ドメイン(diary-domain)

`spec.md`のAssumptionsで確定した範囲(v1はモード限定・過去日記の想起は範囲外・一覧UIは範囲外)を前提に、
既存ドメイン(`017-chat-memory`、`015-paper-qa-chat`、`023-daily-summary-notification`)の実装を
直接調べた上で、技術的な未決定事項をここで解消する。

## Decision 1: バックグラウンド処理の起点は tool ではなく ADR-0003 前処理/後処理

**Decision**: 日記モード中の会話をLLMに能動的に「記録して」と呼ばせるtoolは追加しない。
`017-chat-memory`と同じく、`/api/chat`のADR-0003後処理段(`api/app.py`の`on_complete`)から
バックグラウンドタスクとして日記の更新を行う。

**Rationale**: `chat_agent.py`のdocstringが明記しているとおり、「応答生成モデルに能動的なtool呼び出しを
期待するのは信頼性が低い」という理由で017は記憶の想起・抽出をどちらもメインのチャットエージェントの
外側で完結させている。日記も同じ性質(会話の裏側で静かに記録される)であり、同じ理由がそのまま当てはまる。
`_extract_memory_task`(`api/app.py`)と並ぶ形で`_extract_diary_task`を追加し、
`asyncio.create_task`でfire-and-forget実行する。

**Alternatives considered**: `save_diary_entry`のようなtoolをLLMに呼ばせる案は、015/013の
`save_paper`/`save_ir_document`と対称的で一見自然に見えるが、あれらは「ユーザーが明示的にURLやdocIDを
貼った」という明確なトリガーがある。日記は「日記モード中の会話全部」が対象で明確なトリガーが無いため、
tool呼び出し忘れ(信頼性の問題)が017と同じ理由で起きうる。不採用。

## Decision 2: ログ層(DiaryEvent)+現在状態層(DiaryRecord)を維持するが、現在状態はDBカラムのみ

**Decision**: `017-chat-memory`と同じログ層(追記のみ)+現在状態層(LLMによる読み直し)の二層構造を
採用する。ただし現在状態層は`memory/<slug>.md`のようなファイルにはせず、`DiaryRecord.content`という
DBカラムに留める。

**Rationale**: 017が現在状態をファイルにしているのは、そのファイルが「会話に読み込ませる実体」
(想起時にそのまま返す文字列)として直接利用されるため。日記はv1で想起機能自体を範囲外にした
(spec.mdのAssumptions参照)ため、ファイルを読み込む消費者がv1には存在しない。存在しない消費者のために
ファイルI/O層を作るのはYAGNI(憲章 原則II)に反する。DBカラムなら`023-daily-summary-notification`の
`DailySummaryRecord.content`と同じ「単純な文字列カラム」パターンで十分。

ログ層自体(`DiaryEvent`)は残す: 1ターンごとに最新の会話だけでその日のエントリを書き直すと、
その日の前半の会話内容が失われる(LLMは直前ターンの情報しか見られない)。017がログを全件累積して
rewriteに渡しているのと同じ理由で、その日のログ全件を毎回rewriterに渡す必要がある。

**Alternatives considered**: `DiaryRecord.content`への素朴な文字列追記(ログ層・LLM rewriteなし)も
検討したが、会話の断片をただ連結するだけでは017が避けた「読みにくい生ログ」になり、「日記」としての
体裁を保てない。LLMによる読み直し(rewrite)は必須と判断した。

**将来のための伏線**: 想起機能(過去の日記をチャットで参照する)がv1後に必要になった場合、
`DiaryRecord.content`をDBから直接読んで返すだけで足りる可能性が高く、ファイル層への移行が
必須ではない。移行が必要になった場合は017のパターンをそのまま踏襲すればよい。

## Decision 3: 「記憶に値するか」の判定ステップは省略

**Decision**: 017の`MemoryExtractor`(`worth_remembering`判定+テーマ分類)に相当するLLM呼び出しは
日記には作らない。日記モード中の会話は無条件に`DiaryEvent`として追記する。

**Rationale**: `spec.md`のFR-002/FR-008が明記するとおり、日記モード中の会話は原則すべて記録対象
(017のような選別ステップは意味を持たない、`spec.draft.md`の「背景・判断」で最初から指摘されていた
点)。テーマへのオープンセット分類も、日記のキーが「今日の日付」で自明に決まるため不要
(同じく`spec.draft.md`で先に判断済み)。結果として、LLM呼び出しは「rewrite」1回だけで済む
(017は「extract」+「rewrite」で2回)。

## Decision 4: AG-UI state は既存の`PaperModeState`を汎用化して拡張する

**Decision**: `agent/chat_agent.py`の`PaperModeState`(`active_paper: ActivePaper | None`のみ持つ)を
`ChatUIState`に改名し、`diary_mode: bool = False`フィールドを追加する。`ChatDeps.state`の型・
フロントエンドの`useChatAgent.ts`の`PaperModeState`インターフェース・`App.tsx`の参照箇所を
同じ改名に追従させる。

**Rationale**: `spec.draft.md`の「UI設計」セクションが最初から`ChatUIState { paper_mode, diary_mode }`
という設計を提示していた。実装済みの`PaperModeState`は`active_paper`1フィールドのみのため、素直に
「Paper」を冠したままdiary_modeを生やすとクラス名と実体が食い違う。影響範囲は限定的
(`chat_agent.py`/`api/app.py`/`useChatAgent.ts`/`App.tsx`の型参照のみ、DBスキーマやAPIエンドポイントの
形は変わらない)ため、改名コストは小さい。

論文モードとの共存(spec.mdのFR-006、両モードは排他ではない)は、両方とも同じstateオブジェクトの
異なるフィールドとして表現されることで自然に満たされる(017のようにstateを持たない仕組みとは異なり、
015のようにAG-UI stateを使う理由は「チャット画面にモードを常時表示したい」というUI要件のため)。

**Alternatives considered**: `PaperModeState`はそのまま残し、`ChatDeps`に`diary_mode: bool`を
別フィールドとして追加する案も検討した。しかしAG-UI の state は`RunAgentInput.state`⇄
`StateSnapshotEvent`という単一のJSONオブジェクトとして往復する仕組み(`ChatDeps.state`属性)であり、
`ChatDeps`に複数のstate風フィールドを生やすと「どちらがAG-UI stateとして同期されるのか」が
曖昧になる(`recalled_memory`は明示的にstateではないとdocstringに書かれている、この非対称性を
増やしたくない)。1つのstateオブジェクトにまとめる方が既存の設計意図に忠実。

## Decision 5: 日付境界は`daily_summary.timezone`設定を再利用する

**Decision**: 新しい`DiarySettings`は作らない。「今日」の判定には既存の
`settings.daily_summary.timezone`(既定`Asia/Tokyo`)と、`services/daily_summary.py`の
`local_day_bounds_utc`と同型のロジック(または直接呼び出し)を使う。

**Rationale**: 「生活時間の区切りとしてのJST」という考え方は023で既に確立済みであり、日記も同じ
「今日」の概念を指す。専用設定を増やすより、既存の1箇所を指し示す方がYAGNIに合致し、将来
タイムゾーンを変える運用になった場合も1箇所の変更で済む。`local_day_bounds_utc`自体は
`services/daily_summary.py`にあるが、日付計算(JST変換して`date`を得る部分)は日次サマリー固有の
「範囲」計算とは別の関心事のため、共通の小さいヘルパー(例: `services/daily_summary.py`から
`local_today(tz_name)`のような形で切り出す、または`services/diary.py`に複製せず import する)は
実装時(`/speckit-tasks`以降)に決定する。

**Alternatives considered**: 新規`DiarySettings.timezone`フィールドを増やす案は、既に1箇所に
決定済みの値をもう1箇所に複製するだけで、値がズレた場合に023と019で「今日」の境界が食い違う
バグを生みうる。不採用。

## Decision 6: モデル選択

**Decision**: 日記rewriterは`build_model(settings)`(引数無し、`settings.llm.model_id`=メインの
チャットモデル)を使う。専用の軽量モデルは指定しない。

**Rationale**: `agent/memory_extract.py`の`build_memory_extract_agent`/`build_memory_rewrite_agent`が
同じくメインモデルを使っており(`recall`だけが軽量な`recall_model_id`を使う非対称な理由は「単純な
テーマ照合タスク」だから、`settings.py`のMemorySettings docstring参照)、日記のrewriteは
「複数の会話断片を自然な日記文章にまとめる」という017のrewriteと同種の作業のため、同じ判断基準が
そのまま当てはまる。

## 未解決のまま残す事項(実装時に決定)

- `local_today(tz_name)`ヘルパーの正確な配置場所(`services/daily_summary.py`から共通化するか、
  `services/diary.py`に置くか)
- `ChatUIState`への改名の正確な移行手順(1コミットで全箇所を変更するか、段階的にやるか)
- 日記エントリの`Item.title`/`Item.summary`の具体的な生成規則(例: `f"{date}の日記"`固定か、
  rewriter出力から一部を流用するか)
