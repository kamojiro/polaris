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

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 全体の整合性確認とドキュメント更新

- [X] T020 `uv run nox`(fix/typecheck/cspell/test)を実行し、クリーンであることを確認する
- [X] T021 `cd frontend && npx tsc -b`を実行し、型チェックが通ることを確認する
- [X] T022 `quickstart.md`の全シナリオ(1〜3)+回帰確認を実機で確認する
- [X] T023 [P] `specs/README.md`の019行のステータスを更新し(実装完了後)、実装順の一覧からも外す(023実装時の更新パターンを踏襲)
- [X] T024 [P] `specs/019-diary-domain/spec.md`または`spec.draft.md`に実装状況の追記を行う(023の「実装状況」セクションと同じ形式)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 依存なし、即着手可能
- **Foundational (Phase 2)**: Setup完了後。全User Storyをブロックする
- **User Stories (Phase 3-5)**: Foundational完了後に着手可能。優先順位どおり P1→P2→P3 の順で進めるのが推奨(P2はP1の実装に依存する内容の検証が中心、P3はP1で作った最小トグルの上にUIを足すため)
- **Polish (Phase 6)**: 実施したいUser Storyがすべて完了した後

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完了後に着手可能。他Storyへの依存なし
- **User Story 2 (P2)**: Foundational完了後に着手可能だが、実質的にはUser Story 1(T011)の実装を前提に検証するテスト中心の内容のため、P1の後に行うのが自然
- **User Story 3 (P3)**: Foundational完了後に着手可能。P1のT014(最小トグル)を土台にUIを拡張するため、P1の後に行うのが自然

### Parallel Opportunities

- T004・T005([P]付きFoundationalタスク)は互いに異なるファイルのため並行実行可能
- T008・T009([P]付きUS1テスト)は並行実行可能
- T015([P]付きUS2テスト)はT008系のテストファイルと同じファイルへの追記のため、T008完了後に着手する(逐次)
- T019([P]付きUS3のCSS)はT018と異なるファイルのため並行実行可能
- T023・T024(Polishのドキュメント更新)は互いに異なるファイルのため並行実行可能

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
5. Polish → 全体のnox/quickstart確認、ドキュメント更新

---

## Notes

- [P]タスク = 別ファイル・依存なし
- [Story]ラベルはUser Storyへのトレーサビリティのため
- 各タスク完了後にコミットする(このプロジェクトの慣例、`uv run nox`がクリーンな状態を保つ)
- チェックポイントごとに`quickstart.md`該当シナリオで単独検証してから次に進む
