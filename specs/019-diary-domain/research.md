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

## Decision 7: バックフィルの日付推定は専用の軽量エージェント(`DiaryDateInferrer`)が担う

**Decision**: `record_diary_turn`に`target_date: date | None`引数を追加する点はそのまま(`data-model.md`
参照)が、その値を作る主体は**メインのチャットエージェントではなく**、新規の軽量エージェント
`DiaryDateInferrer`(`agent/diary_date_infer.py`)にする。`api/app.py::_record_diary_task`が
`record_diary_turn`を呼ぶ前に`DiaryDateInferrer.infer(user_text, assistant_text, today=local_today(...))`
を呼び、構造化出力`{ target_date: date | None }`を得て、それをそのまま`record_diary_turn`へ渡す。
推定できなければ`None`(=`record_diary_turn`側で`local_today()`にフォールバック)。専用の日付パーサー・
確認UIは作らない(`spec.md` Assumptions)。

**Rationale**: 当初「メインのチャットLLMが推定して渡す」という書き方をしていたが、日記の記録処理は
Decision 1のとおりtool呼び出しではなく`on_complete`側のバックグラウンド処理であり、メインの
チャットエージェントの出力(ユーザーへの応答文)から構造化された日付情報を安全に取り出す経路が
無い。017の`MemoryExtractor`(会話ターンを見て構造化出力を返す軽量エージェント)と同じパターンを
踏襲し、「日記モード中の全ターンについて、まず日付推定の軽量LLM呼び出しを挟む」設計にする。
`agent/extract_metadata.py`系と同じくreasoningは無効化した構造化抽出タスクとして扱う(単純な
分類・抽出であり、023のような複数ドメイン横断の総合判断ではないため)。「今日」の日付
(`local_today()`)を入力に含めることで、「先週の水曜」のような相対表現を絶対日付に解決できる
ようにする。

**Alternatives considered**:
- 専用の日付抽出ステップ自体を設けず正規表現でパースする案は、「先週の水曜」のような相対表現の
  解釈精度が低く不採用(当初案、Decision 1の設計を見落としていたための誤り)
- メインのチャットエージェントに`target_date`を明示させる案(例: 応答メッセージに埋め込む、または
  新規tool経由)も検討したが、前者はユーザー向け応答文に構造化データを混ぜる不自然な設計になり、
  後者はDecision 1で明示的に避けた「日記記録をtool呼び出し依存にする」設計に逆戻りするため不採用

## Decision 8: 読み取りtoolは`get_diary_range(start_date, end_date)`1本に統合

**Decision**: 単日・期間どちらの読み取りも`get_diary_range(start_date: date, end_date: date)`という
単一のtoolで扱う(単日は`start_date == end_date`)。`get_diary_by_date`/`get_diary_month`のような
複数toolへの分割は採らない。読み取り元は`DiaryRecord`テーブルへの`entry_date BETWEEN`範囲クエリの
みとし、月次markdownファイルのようなものは経由しない(v1で採用しなかったファイル層をここでも
導入しない、Decision 2と一貫)。期間の上限は62日とし、超える場合はLLMに範囲を絞るよう伝えて弾く。

**Rationale**: toolを2本に分けても「1日だけ見る」は「期間が1日の特殊形」でしかなく、実質的な処理は
共通(範囲クエリ)になる。1本にまとめる方がtool定義・呼び出し判断のどちらもシンプル。月境界を
またぐ範囲(7月末〜8月頭等)でも、DBの日付インデックスによる範囲クエリなら複数ファイルを
またいでスライスする実装が要らない。62日という上限は`get_paper_full_text`と同種の「全文を
コンテキストに渡す」toolである以上、広すぎる範囲によるコンテキスト肥大化(`specs/IDEAS.md`に
記録した問題と同じ轍)を避けるための最低限のガード。

**Alternatives considered**: `get_diary_by_date`(単日)と`get_diary_month`(月単位)への分割は、
月境界をまたぐ質問(「先週」が月をまたぐ場合等)を素直に扱えず、結局範囲クエリのロジックを
どちらのtoolにも持たせる二度手間になるため不採用。

**ADR-0012との関係**: `get_diary_range`は`get_paper_full_text`と同じ「全文をコンテキストに渡す」
性質のtoolのため、`docs/adr/0012-trim-stale-tool-results-from-history.md`の
`FULL_TEXT_TOOL_NAMES`(`src/polaris/services/history_trim.py`)にツール名を追加する。書き込み系
(`record_diary_turn`)には手を加えない。

**実装時の訂正(2026-08-30)**: 実機検証で「今月の日記をまとめて教えて」と尋ねたところ、
`get_diary_range(start_date=2026-01-01, end_date=2026-01-27)`のように**別の年月**(2026年1月)
として解釈されるバグを確認した。原因は、メインのチャットエージェントに「今日の日付」を伝える
仕組みがどこにも無く、「今月」「先週」のような相対表現をLLMが正しく絶対日付へ変換できなかった
ため。`_register_diary_read_tools`に`@agent.instructions`の動的instructions(`_today_instructions`、
`local_today()`を使う)を追加し、毎ターン「今日の日付」を伝えるようにして解消した。

さらに、62日超過ガード(FR-011)自体は正しく機能していたが、「2025年1月1日から今日までの日記を
全部見せて」のような極端な期間を尋ねると、モデルが案内メッセージに従ってユーザーに絞り込みを
促す代わりに、31日ずつの範囲へ自律的に分割して20ヶ月分を律儀に遡り続け、約30回`get_diary_range`を
呼び出す(実測、$0.01強)という非効率な挙動を確認した。結果自体は正しかった(実在する記録のみを
正しく報告した)が、実用上は避けたい。`_INSTRUCTIONS`に「期間超過のメッセージを受け取ったら
分割して呼び直すのではなく、その旨をユーザーに伝えて期間を絞ってもらう」旨を追記して対処した。

もう1点、日記モード中に日記モードとは無関係な発言(「今日は掃除をした」)をした際、データ自体は
正しく記録される(バックグラウンド処理は`deps.state.diary_mode`をチェックするだけでメインの
チャットエージェントを経由しない)一方、メインのチャットエージェントは自分が「日記モード中」で
あることを一切知らないため、「日記として保存されません」という**誤った案内文**をユーザーに
返してしまう不整合を確認した(データは正しいが、応答テキストが紛らわしい)。`_paper_mode_instructions`
(015)と同じパターンで`_diary_mode_instructions`を追加し、`deps.state.diary_mode`が`True`の間は
「現在日記モード中で、発言は裏側で自動記録されている」旨を動的instructionsとして伝えることで解消した。

## Decision 9: 執筆中パネルはDBの`updated_at`降順クエリで、専用エンドポイント`GET /api/diary/recent`を新設

**Decision**: パネル表示用に軽量な読み取り専用エンドポイント`GET /api/diary/recent?count=3`を追加する。
実装は「`DiaryRecord`を`updated_at`降順で1件(アンカー)取得 → `entry_date < アンカー`を`entry_date`
降順で`count - 1`件取得」という2段クエリ。日付計算(`アンカー日 - 1日`等)は行わない。

**Rationale**: アンカーを「今日」固定にすると、バックフィル(Decision 7)で過去日を書いた直後に
パネルへ反映されない(今日のエントリが変わっていないため)。`updated_at`降順の1件を素直にアンカーに
すれば「今まさに書いている(=直前に更新された)日」を常に正しく指せる。バックフィルで飛び石の
日付になっていても、`entry_date <アンカー`を降順LIMITで取るだけで「直前に存在する日」を自然に
拾えるため、日付計算ロジックを別途持つ必要がない。既存の`GET /api/daily-summary/latest`と同じ
「読み取り専用の軽量エンドポイント」パターンを踏襲する。

**Rationale(表示トリガー)**: `diary_mode`をONにした瞬間ではなく、日記モード中に最初のメッセージを
送信しターンが完了した後にパネルを表示する。モードに入っただけの時点では当日分がまだ存在せず、
空の枠を見せることになって座りが悪い。モード切替時専用の初期フェッチを別に用意する必要も無い。

**実装時の訂正(2026-08-30)**: 当初「使用量表示等と同じ、ターン完了後に再取得する仕組みにそのまま
乗る」と書いたが、これは誤りだった。使用量イベント(`_emit_usage_event`)はストリーム自体の中で
`yield`されるため、ストリーム完了時点で値が確定している。しかし日記の記録(`_record_diary_task`)は
`services/memory.py`の`_extract_memory_task`と同じ`asyncio.create_task`によるfire-and-forgetで
設計しており、ストリーム完了(=フロントの`fetchDiaryRecent()`発火)を待たずに完了する保証が無い。
実機検証で、パネルが1ターン古い内容を表示するレースコンディションとして実際に顕在化した。対応として、
日記の記録処理(`_record_diary_task`)に限り`asyncio.create_task`ではなく`on_complete`内で直接
`await`し、DB書き込みを完了させてからストリームを終える設計に変更した(`api/app.py`参照)。
017の記憶抽出(`_extract_memory_task`)は即座の鮮度を要求するUIが無いため、fire-and-forgetのまま
変更していない。

**Alternatives considered**: AG-UI stateに「今アクティブな日付」を明示的に持たせ、チャット側から
フロントへ伝える案も検討したが、バックフィルにより「今書いている日」が発話ターンごとに変わりうる
ため、状態同期のタイミング調整が複雑になる。`updated_at`降順クエリなら、ターン完了後に同じ
エンドポイントを叩き直すだけで常に正しいアンカーが取れるため、この複雑さを回避できる。

## Decision 10: 日記モードのON/OFFをチャットからも切り替えられるようにする(`set_diary_mode`、2026-08-31追加)

**Decision**: 当初、日記モードのON/OFFはUIのトグルボタン専用とし、チャットのtoolでは制御できない
設計にしていた(v1〜User Story 6時点)。実運用フィードバックで、「日記モードになって」のように
チャットで切り替えたいという要望が確認できたため、`exit_paper_mode`と同じ「state変更専用tool」
パターンで`set_diary_mode(enabled: bool)`を追加した(`chat_agent.py`)。日記モードには論文モードの
ような「対象を特定する」概念が無い(ON/OFFの2値のみ)ため、論文モードのtool群とは統合しない
独立したtoolにする(将来複数モードを1つのtoolに統合する案も検討したが、モードごとに必要な引数の
形が異なりすぎるため見送った)。

**Rationale(副次的な不具合の解消)**: 実機検証で、日記モードを制御する手段がモデルに一切無い状態で
「日記モードになって」と言われると、モデルが対応方法に迷い続けてreasoningトークンを大量消費し
(実測: 3177トークン)、1ターンの完了トークン予算(OpenRouterのprovider default)をreasoningだけで
使い切って"Model token limit (provider default) exceeded before any response was generated"
というエラーになる不具合の一因になっていることを確認した。加えて、対応手段が無いのにモデルが
「日記モードに入りました」と**実際にはstateを変えていないのに変えたかのような虚偽の確認**を
返す不具合も確認した。`set_diary_mode`を追加してモデルに実際の対応手段を与えたところ、同じ会話を
再現実験したら reasoning_tokens が 3177→132、1616→303 まで減少し(`_CHAT_MODEL_SETTINGS`の
上限設定と合わせた効果)、確認応答も実際のstate変更を伴う正しいものになった。

**Alternatives considered**: 「モードはUIのボタンでのみ変更できる」とシステムプロンプトに明記し、
チャットからの切り替え要求には案内で応えるだけに留める案も検討した(reasoning消費は多少減らせる)。
しかし実際にチャットから切り替えたいというユーザー要望があったため、案内だけで終わらせず実際に
機能させる方を選んだ。

## Decision 11: メインのチャットエージェントに完了トークン予算の上限を設ける(`_CHAT_MODEL_SETTINGS`、2026-08-31追加)

**Decision**: `agent/chat_agent.py`に`_CHAT_MODEL_SETTINGS = OpenRouterModelSettings(max_tokens=8000,
openrouter_reasoning={"max_tokens": 3000})`を追加し、`build_chat_agent`の`Agent(...)`に
`model_settings=`として渡す。reasoning自体は無効化しない(メインエージェントは複雑な判断が
必要なため意図的にreasoning有効のまま、`agent/memory_extract.py`等の構造化抽出系とは違う)。

**Rationale**: Decision 10の不具合(対応手段の無い要求への迷走)は「モデルへの手段の提供」で
大きく緩和できたが、根本的には「reasoning予算・完了予算がOpenRouterのprovider default(明示しない
限りルーティング先プロバイダごとに変動しうる)に無制限に委ねられている」こと自体がリスクである
ため、上限を明示して安全網とする。`OpenRouterReasoning`は`effort`(OpenAI形式)と`max_tokens`
(Anthropic形式)が排他(`pydantic_ai/models/openrouter.py`のdocstring参照)なので、今回は
`max_tokens`形式を選んだ。他の補助エージェント(`agent/memory_extract.py`等)は既に
`openrouter_reasoning={"enabled": False}`で完全無効化しているため、この上限設定と競合しない
(それぞれ別のAgentインスタンス・別のmodel_settingsを持つため)。

## Decision 12: `set_diary_mode`呼び出しターン自体が日記内容として記録される不具合の修正(2026-08-31追加)

**Decision**: Decision 10で`set_diary_mode`を追加した直後の実機検証で、「日記モードになって」という
モード切り替えの発話自体が、その日の日記に(意味のあるアシスタントの空返答も含めて)混入する不具合を
発見した。当初`api/app.py`の`on_complete`側で「このターンで`set_diary_mode`が呼ばれていたら
そのターンはまるごと記録しない」という条件を試みたが、これだと「日記モードになって、今日は
新しいカフェに行った」のように**モード切り替えと実際の日記内容が同じ発話に同居するケース**で、
実内容まで丸ごと記録しないことになってしまう(なお終了側`enabled=False`は`ctx.deps.state.diary_mode`が
tool実行中にFalseへ変わるため、`on_complete`の`if deps.state.diary_mode:`判定で元々自動的に
除外されており、混入の実害は開始側`enabled=True`のみだった)。

最終的に、記録自体は常に行う(`on_complete`側の条件は変更しない)方針とし、代わりに
`agent/diary_rewrite.py`の`_REWRITE_INSTRUCTIONS`に「モード切り替えの発話自体やそれに対する
定型応答は日記本文に含めず無視し、同じ断片に実内容が含まれていればそちらだけを採用する」旨を
追記した。日記本文の生成はもともと生の断片を単純結合ではなくLLMで要約・再構成する設計
(Decision 2)なので、記録の可否を判定する層ではなく、内容を判断する層(rewriter)にこの
判断を委ねるのが自然。

**Verification**: 3パターンで再現確認(`rewriter.rewrite`を直接叩くスクリプト)。
(1)「日記モードになって」のみ → `（今日の出来事なし）`(以前は無関係な過去の会話内容が
混入した虚偽の文章になっていた)。(2)「日記モードになって、今日は新しいカフェに行った」
(同一発話に同居) → `今日は新しいカフェに行った。`(モード切り替え部分は正しく除外)。
(3)モード切り替えのみのターンの後、別ターンで実内容 → `新しいカフェに行った。`
いずれも意図通り。ライブブラウザでの同一発話同居ケースの検証もE2Eで実施し、想定通り
実内容のみがパネルに反映されることを確認した。

## 未解決のまま残す事項(実装時に決定)

(v1実装時点の未解決事項はすべて実装時に解消済み。User Story 4-6追加分の未解決事項も実装時に解消: `GET /api/diary/recent`は`entry_date`昇順の配列+末尾がアンカーという形に決定、`get_diary_range`の62日超過時は日本語の案内メッセージ文字列を返す形に決定)
