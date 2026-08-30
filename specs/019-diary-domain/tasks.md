---

description: "Task list template for feature implementation"
---

# Tasks: 日記ドメイン(diary-domain)

**Input**: Design documents from `/specs/019-diary-domain/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/state.md, quickstart.md

**Tests**: 既存ドメイン(017/023など)がすべて`tests/db/`・`tests/services/`にユニットテストを持つ慣例に
合わせ、テストタスクを含める。

**Organization**: `spec.md`のUser Story(P1/P2/P3)ごとにグルーピングする。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並行実行可能(別ファイル、他の未完了タスクへの依存が無い)
- **[Story]**: どのUser Storyに属するか(US1/US2/US3)

## Path Conventions

既存の単一プロジェクト構成(`src/polaris/`、`frontend/src/`、`tests/`)にそのまま追加する。
新規プロジェクト構造は無し(`plan.md`のProject Structure参照)。

---

## Phase 1: Setup

**Purpose**: 新規依存関係・新規プロジェクト初期化は無し(既存リポジトリへの機能追加のみ)。

- [X] T001 `data-model.md`と`research.md`を読み直し、実装前提を最終確認する(新規ライブラリ追加・lint設定変更は無いことの確認のみ)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 全User Storyが依存する土台(データモデル・stateの形)。ここが終わるまでどのUser Storyも着手できない。

**⚠️ CRITICAL**: このフェーズ完了までUser Story実装は開始しない

- [X] T002 `src/polaris/domain/entities.py`に`ItemType.diary`、`DiaryRecord`、`DiaryEvent`を追加する(`data-model.md`のエンティティ定義どおり)
- [X] T003 `src/polaris/db/diary_repository.py`を新規作成し、`DiaryRepository`(`append_event`/`list_events`/`get_record`/`upsert_record`)を実装する(T002に依存、`db/memory_repository.py`と同じ「メソッドごとにSessionを開く」パターン)
- [X] T004 [P] `src/polaris/services/daily_summary.py`に`local_today(tz_name: str) -> date`ヘルパーを追加する(既存の`local_day_bounds_utc`から日付部分だけを取り出す形、`research.md` Decision 5)
- [X] T005 [P] `src/polaris/agent/chat_agent.py`の`PaperModeState`を`ChatUIState`に改名し、`diary_mode: bool = False`フィールドを追加する。`ChatDeps.state`の型注釈、`_register_paper_qa_tools`内の参照箇所も追従させる(`research.md` Decision 4)
- [X] T006 `frontend/src/useChatAgent.ts`の`PaperModeState`インターフェースを`ChatUIState`に改名し、`diary_mode: boolean`フィールドを追加する(T005に対応するフロント側の型、`contracts/state.md`参照)
- [X] T007 `frontend/src/App.tsx`内の`PaperModeState`型参照を`ChatUIState`に追従させる(挙動変更なし、コンパイルが通ることを確認)

**Checkpoint**: ここまで完了すれば、各User Storyの実装を開始できる

---

## Phase 3: User Story 1 - 日記モードでの会話がその日のエントリになる (Priority: P1) 🎯 MVP

**Goal**: ユーザーが日記モードに入って会話すると、その日のエントリが自動的に作成・更新される

**Independent Test**: `quickstart.md`シナリオ1(日記モードON→会話→`diary_records`テーブルを直接確認)

### Tests for User Story 1

- [X] T008 [P] [US1] `tests/db/test_diary_repository.py`を新規作成し、`append_event`/`list_events`/`upsert_record`(新規作成)のテストを書く
- [X] T009 [P] [US1] `tests/services/test_diary.py`を新規作成し、フェイクの`DiaryRewriter`+実DBで「日記モード中の1ターンでエントリが作成される」ことを検証するテストを書く(`tests/services/test_memory.py`と同型)

### Implementation for User Story 1

- [X] T010 [P] [US1] `src/polaris/agent/diary_rewrite.py`を新規作成し、`DiaryRewriter`(Protocol)+`build_diary_rewrite_agent`+`AgentDiaryRewriter`を実装する(`agent/memory_extract.py`のrewrite半分と同型、`build_model(settings)`でメインモデルを使う。`research.md` Decision 6)
- [X] T011 [US1] `src/polaris/services/diary.py`を新規作成し、`record_diary_turn(user_text, assistant_text, *, turn_id, rewriter, repo, settings)`を実装する。`DiaryEvent`追記→当日の全イベントを`rewriter`に渡してrewrite→`DiaryRecord`をupsert、の流れ(T003・T004・T010に依存)
- [X] T012 [US1] `src/polaris/api/app.py`に`_diary_repo`/`_diary_rewriter`の構築を追加し、`on_complete`内で`deps.state.diary_mode`が`True`の場合に`_extract_diary_task`(fire-and-forget)を起動する処理を追加する(既存の`_extract_memory_task`と並列、T011に依存)
- [X] T013 [US1] `frontend/src/useChatAgent.ts`に`toggleDiaryMode()`(`agent.setState`で`diary_mode`をON/OFFする、`exitPaperMode`と同型)を追加する(T006に依存)
- [X] T014 [US1] `frontend/src/App.tsx`の入力欄ツールバーに、日記モードをトグルする最小限のボタンを追加する(見た目の作り込みはUS3で行う。ここではON/OFFが機能することが目的)

**Checkpoint**: 日記モードで会話するとその日のエントリが作られる、という中核機能がこの時点で単独動作する

---

## Phase 4: User Story 2 - 同じ日に何度もモードへ出入りしても1エントリに保たれる (Priority: P2)

**Goal**: 日記モードへの複数回の出入りが、その日のエントリを1件に保ったまま内容を積み上げる

**Independent Test**: `quickstart.md`シナリオ2(ON→OFF→別の話題→ON→追加の会話→`diary_records`の件数が1のまま)

### Tests for User Story 2

- [X] T015 [P] [US2] `tests/db/test_diary_repository.py`に、同じ`entry_date`で`upsert_record`を複数回呼んでも行が増えないことを検証するテストを追加する
- [X] T016 [US2] `tests/services/test_diary.py`に、同じ日に`record_diary_turn`を複数回(間に他の会話を挟んでも)呼んだ結果、`DiaryRecord`が1件のまま`content`に両方のやり取りが反映されることを検証するテストを追加する

### Implementation for User Story 2

- [X] T017 [US2] User Story 1の実装(T011の`upsert_record`呼び出し、`entry_date`のunique制約)で本要件が既に満たされているかをT015/T016で確認し、満たされていなければ`services/diary.py`/`db/diary_repository.py`を修正する

**Checkpoint**: 1日1エントリの保証が、実装(T011)とテスト(T015/T016)の両面で確認できる

---

## Phase 5: User Story 3 - 今どのモードにいるか画面で判別できる (Priority: P3)

**Goal**: 日記モードのON/OFFが画面上で常に判別できる。論文モードとの同時表示にも対応する

**Independent Test**: `quickstart.md`シナリオ3(トグル操作に連動した表示の目視確認、論文モードとの同時ON確認)

### Implementation for User Story 3

- [X] T018 [US3] `frontend/src/App.tsx`に日記モードのチップ表示(「📔 日記モード」+`×`で終了)を追加する。既存の論文モードバッジ(`paperMode.active_paper`)と同じ箇所に並べて表示し、両方が同時に表示されうることを確認する(T014で作った最小トグルボタンをこのチップ表示と統合してよい)
- [X] T019 [P] [US3] `frontend/src/styles.css`に日記モードチップ用のCSSブロックを追加する(既存の`.paper-mode-badge`と近い見た目、色味は区別する)

**Checkpoint**: 全User Storyが独立に動作確認できる状態になる

---

## Phase 6: Polish & Cross-Cutting Concerns (v1)

**Purpose**: 全体の整合性確認とドキュメント更新

- [X] T020 `uv run nox`(fix/typecheck/cspell/test)を実行し、クリーンであることを確認する
- [X] T021 `cd frontend && npx tsc -b`を実行し、型チェックが通ることを確認する
- [X] T022 `quickstart.md`の全シナリオ(1〜3)+回帰確認を実機で確認する
- [X] T023 [P] `specs/README.md`の019行のステータスを更新し(実装完了後)、実装順の一覧からも外す(023実装時の更新パターンを踏襲)
- [X] T024 [P] `specs/019-diary-domain/spec.md`または`spec.draft.md`に実装状況の追記を行う(023の「実装状況」セクションと同じ形式)

---

## Phase 7: User Story 4 - 過去日を指定して日記を書く(バックフィル) (Priority: P4)

**Goal**: 日記モード中の発話から過去の日付が推定できれば、当日ではなくその日のエントリが更新される

**Independent Test**: `quickstart.md`シナリオ4(過去日を示唆する発話→該当日のエントリが更新される)

### Tests for User Story 4

- [X] T025 [P] [US4] `tests/services/test_diary.py`に、フェイクの`DiaryDateInferrer`が過去日を返した場合に
  `record_diary_turn`がその日付の`DiaryRecord`を更新し、当日のエントリは作られないことを検証するテストを追加する
- [X] T026 [P] [US4] 同ファイルに、フェイクが`None`を返した場合(推定できない)は`local_today()`が
  使われることを検証するテストを追加する(既存テストが暗黙にこれを検証していなければ追加)

### Implementation for User Story 4

- [X] T027 [P] [US4] `src/polaris/agent/diary_date_infer.py`を新規作成し、`DiaryDateInferrer`(Protocol)+
  `DateInferenceResult`+`build_diary_date_infer_agent`+`AgentDiaryDateInferrer`を実装する
  (`agent/extract_metadata.py`と同じ構造化抽出パターン、reasoning無効化。`data-model.md`参照)
- [X] T028 [US4] `src/polaris/services/diary.py`の`record_diary_turn`に`target_date: date | None = None`
  引数を追加する。指定されればその日付を、`None`なら既存どおり`local_today()`を対象にする(T025・T026・T027に依存)
- [X] T029 [US4] `src/polaris/api/app.py`に`_diary_date_inferrer`の構築を追加し、`_record_diary_task`内で
  `record_diary_turn`を呼ぶ前に`DiaryDateInferrer.infer(...)`を呼んで`target_date`を渡すよう配線する(T028に依存)

**Checkpoint**: 過去日を示唆する発話が正しく該当日のエントリに反映される、という機能がこの時点で単独動作する

---

## Phase 8: User Story 5 - 期間を指定して日記を読み返す (Priority: P5)

**Goal**: チャットで単日・複数日の日記エントリの内容をもとに回答が得られる

**Independent Test**: `quickstart.md`シナリオ5(単日・期間の問い合わせ、62日超のガード)

### Tests for User Story 5

- [X] T030 [P] [US5] `tests/db/test_diary_repository.py`に`list_records_in_range`(範囲内のみ返す、
  境界値を含む)のテストを追加する

### Implementation for User Story 5

- [X] T031 [US5] `src/polaris/db/diary_repository.py`に`list_records_in_range(start_date, end_date)`
  を実装する(`data-model.md`参照、T030に依存)
- [X] T032 [US5] `src/polaris/agent/chat_agent.py`に`get_diary_range(start_date, end_date)`tool
  (`tool_plain`)を追加する。62日を超える場合は例外を投げず案内文字列を返す(`contracts/diary-read-write.md`参照、T031に依存)。`_INSTRUCTIONS`に「日記の内容について聞かれたらget_diary_rangeを使う」旨の
  1文を追加する
- [X] T033 [US5] `src/polaris/services/history_trim.py`の`FULL_TEXT_TOOL_NAMES`に`"get_diary_range"`を
  追加する(ADR-0012対応、`research.md` Decision 8)

**Checkpoint**: チャットで日記を読み返せる、という機能がこの時点で単独動作する

---

## Phase 9: User Story 6 - 執筆中の日記をその場で確認できる (Priority: P6)

**Goal**: 日記モードでメッセージを送ると、直近の更新内容を反映したパネルが画面に表示される

**Independent Test**: `quickstart.md`シナリオ6(表示トリガー、アンカーの強調、折りたたみ)

### Implementation for User Story 6

- [X] T034 [P] [US6] `src/polaris/db/diary_repository.py`に`get_latest_updated_record()`と
  `list_records_before(entry_date, *, limit)`を実装する(`data-model.md`参照)
- [X] T035 [US6] `src/polaris/api/app.py`に`GET /api/diary/recent?count=3`を追加する。T034の2メソッドを
  使い、アンカー1件+前後`count - 1`件を返す(`contracts/diary-read-write.md`参照、T034に依存)
- [X] T036 [US6] `frontend/src/useChatAgent.ts`に、日記モードでのターン完了後に`/api/diary/recent`を
  叩き直すロジックを追加する(既存の使用量表示等と同じ「ターン完了後に再取得」パターン、T035に依存)
- [X] T037 [US6] `frontend/src/App.tsx`に執筆中パネル(直近3日、アンカーを強調、折りたたみトグル)を
  追加する。表示トリガーは「日記モード中に最初のメッセージ送信後」(モードONの瞬間には出さない、T036に依存)
- [X] T038 [P] [US6] `frontend/src/styles.css`にパネル用CSSを追加する

**Checkpoint**: 全User Story(P1〜P6)が独立に動作確認できる状態になる

---

## Phase 10: Polish & Cross-Cutting Concerns (User Story 4-6追加分)

- [X] T039 `uv run nox`(fix/typecheck/cspell/test)を実行し、クリーンであることを確認する
- [X] T040 `cd frontend && npx tsc -b`を実行し、型チェックが通ることを確認する
- [X] T041 `quickstart.md`のシナリオ4〜6+回帰確認(シナリオ1〜3が壊れていないこと)を実機で確認する。
  実機検証で以下4件の実バグを発見し、その場で修正・再検証まで完了させた(詳細は`research.md`の
  各Decisionの「実装時の訂正」参照):
  - `agent/diary_date_infer.py`が`date`型を`TYPE_CHECKING`配下でしかimportしておらず、
    Pydanticがランタイムでスキーマを構築できず**サーバー起動時にクラッシュ**していた
    (`--reload`のたびに再クラッシュし、`/api/health`すら無応答になっていた)
  - `_record_diary_task`をfire-and-forgetのままにしていたため、執筆中パネルの再取得が
    DB書き込み完了前に走るレースコンディションがあった → `on_complete`内で直接`await`する方式に変更
  - `get_diary_range`がメインのチャットエージェントの「今日の日付」を知らず、「今月」を別の
    年月と誤解釈していた → `_today_instructions`を追加
  - 62日超過時、モデルが案内に従わず31日ずつに分割して律儀に遡り続け約30回toolを呼んでいた
    → `_INSTRUCTIONS`に「分割して呼び直さない」旨を追記
  - 日記モード中の雑談で、メインのチャットエージェントが自分が日記モード中と知らず
    「日記として保存されません」という誤った案内をしていた(データ自体は正しく記録されていた)
    → `_diary_mode_instructions`を追加
- [X] T042 [P] `specs/019-diary-domain/spec.md`/`spec.draft.md`に、User Story 4-6の実装状況を追記する
- [X] T043 [P] `specs/README.md`の019行の備考を更新する(User Story 4-6が実装されたことを反映)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 依存なし、即着手可能
- **Foundational (Phase 2)**: Setup完了後。全User Storyをブロックする
- **User Stories 1-3 (Phase 3-5)**: Foundational完了後に着手可能。優先順位どおり P1→P2→P3 の順で進めるのが推奨(P2はP1の実装に依存する内容の検証が中心、P3はP1で作った最小トグルの上にUIを足すため)
- **Polish v1 (Phase 6)**: User Story 1-3完了後
- **User Story 4 (Phase 7)**: User Story 1の実装(`record_diary_turn`/`_record_diary_task`)に依存
- **User Story 5 (Phase 8)**: Foundational完了後に着手可能。User Story 1-4への依存なし(読み取り専用の追加機能)
- **User Story 6 (Phase 9)**: User Story 4(バックフィル時のアンカー挙動を正しく扱うため)に依存
- **Polish 追加分 (Phase 10)**: User Story 4-6のうち実施したいものがすべて完了した後

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完了後に着手可能。他Storyへの依存なし
- **User Story 2 (P2)**: Foundational完了後に着手可能だが、実質的にはUser Story 1(T011)の実装を前提に検証するテスト中心の内容のため、P1の後に行うのが自然
- **User Story 3 (P3)**: Foundational完了後に着手可能。P1のT014(最小トグル)を土台にUIを拡張するため、P1の後に行うのが自然
- **User Story 4 (P4)**: User Story 1の`record_diary_turn`/`_record_diary_task`を拡張するため、P1完了後
- **User Story 5 (P5)**: 読み取り専用の独立機能。Foundational完了後ならP1〜P4と並行して進められる
- **User Story 6 (P6)**: アンカーロジック(`updated_at`降順)がUser Story 4のバックフィルと整合する必要があるため、P4の後に行うのが自然

### Parallel Opportunities

- T004・T005([P]付きFoundationalタスク)は互いに異なるファイルのため並行実行可能
- T008・T009([P]付きUS1テスト)は並行実行可能
- T015([P]付きUS2テスト)はT008系のテストファイルと同じファイルへの追記のため、T008完了後に着手する(逐次)
- T019([P]付きUS3のCSS)はT018と異なるファイルのため並行実行可能
- T023・T024(Polishのドキュメント更新)は互いに異なるファイルのため並行実行可能
- T025・T026([P]付きUS4テスト、同じファイルへの追記だが独立した検証観点)・T027([P]付き新規エージェント)は並行実行可能
- T030([P]付きUS5テスト)はUser Story 1-4の完了を待たずに着手可能(読み取り専用の独立機能)
- T034([P]付きUS6のリポジトリメソッド追加)は他のUser Story実装と異なるメソッドのため並行実行可能
- T038([P]付きUS6のCSS)はT037と異なるファイルのため並行実行可能
- T042・T043(Polish追加分のドキュメント更新)は互いに異なるファイルのため並行実行可能

---

## Parallel Example: Foundational

```bash
# T004とT005は別ファイルのため並行実行できる:
Task: "src/polaris/services/daily_summary.py に local_today() を追加"
Task: "src/polaris/agent/chat_agent.py の PaperModeState を ChatUIState に改名"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1(Setup)完了
2. Phase 2(Foundational)完了 — ここが終わるまでP1にも着手できない
3. Phase 3(User Story 1)完了 → `quickstart.md`シナリオ1で単独検証
4. この時点で「日記モードで会話するとエントリが記録される」という中核機能はデモ可能

### Incremental Delivery

1. Setup + Foundational → 土台完成
2. User Story 1 → 単独検証 → MVP
3. User Story 2 → 単独検証(1日1エントリの保証)
4. User Story 3 → 単独検証(UI表示)
5. Polish(v1) → 全体のnox/quickstart確認、ドキュメント更新(ここまでが2026-08-30実装完了分)
6. User Story 4 → 単独検証(バックフィル)
7. User Story 5 → 単独検証(期間読み返し、User Story 1-4と並行しても可)
8. User Story 6 → 単独検証(執筆中パネル、User Story 4完了後)
9. Polish(追加分) → 全体のnox/quickstart確認、ドキュメント更新

---

## Notes

- [P]タスク = 別ファイル・依存なし
- [Story]ラベルはUser Storyへのトレーサビリティのため
- 各タスク完了後にコミットする(このプロジェクトの慣例、`uv run nox`がクリーンな状態を保つ)
- チェックポイントごとに`quickstart.md`該当シナリオで単独検証してから次に進む
