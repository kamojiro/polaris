---

description: "Task list template for feature implementation"
---

# Tasks: 記憶テーマの定期棚卸し(memory-theme-housekeeping)

**Input**: Design documents from `/specs/024-memory-theme-housekeeping/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/memory-housekeeping-api.md, quickstart.md

**Tests**: 既存ドメイン(017/019/023など)がすべて`tests/db/`・`tests/services/`にユニットテストを持つ慣例に
合わせ、テストタスクを含める。CLI・APIエンドポイントは配線のみのためユニットテスト対象外(`023`の
`plan.md`と同じ方針)。フロントエンドのバナーも既存コンポーネント(`DailySummaryBanner.tsx`等)と
同じく単体テストは持たない(手動E2Eは`quickstart.md`でカバー)。

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

- [X] T001 `data-model.md`・`research.md`・`contracts/memory-housekeeping-api.md`を読み直し、実装前提を最終確認する(新規ライブラリ追加・lint設定変更は無いことの確認のみ)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 全User Storyが依存する土台(データモデル・永続化層)。US1がここに書き込み、US2/US3がここを読むため、いずれのUser Storyもこのフェーズ完了まで着手できない。

**⚠️ CRITICAL**: このフェーズ完了までUser Story実装は開始しない

- [X] T002 `src/polaris/domain/entities.py`に`MemoryHousekeepingSuggestion`(SQLModel)を追加する(`data-model.md`のエンティティ定義どおり: `id`/`suggestion_type`/`target_themes`/`detail`/`generated_at`)
- [X] T003 `src/polaris/db/memory_housekeeping_repository.py`を新規作成し、`MemoryHousekeepingRepository`(`replace_all`/`list_latest`)を実装する(T002に依存。`replace_all`は既存行を全削除してから挿入する1トランザクション、`data-model.md`参照。`db/memory_repository.py`と同じ「メソッドごとにSessionを開く」パターン)

**Checkpoint**: ここまで完了すれば、各User Storyの実装を開始できる

---

## Phase 3: User Story 1 - 記憶テーマの整理候補が自動的に検出される (Priority: P1) 🎯 MVP

**Goal**: バッチ処理が全記憶テーマの現在の内容を読み、統合・分割・stale候補を検出してDBに保存する

**Independent Test**: `quickstart.md`シナリオ1〜3(内容が重複するテーマを用意→CLI実行→`memory_housekeeping_suggestions`テーブルを直接確認。0〜1件でもエラーにならないこと、再実行で完全置き換えされることも含む)

### Tests for User Story 1

- [X] T004 [P] [US1] `tests/db/test_memory_housekeeping_repository.py`を新規作成し、`replace_all`(既存行が新しい行で完全に置き換わること、空リストを渡すと既存行が消えること)と`list_latest`のテストを書く
- [X] T005 [P] [US1] `tests/services/test_memory_housekeeping.py`を新規作成し、フェイクの`MemoryHousekeepingDetector`+実DB(tmp)で「全テーマを読み込み、検出結果が保存される」ことを検証するテストを書く。テーマ0件・1件でもエラーにならないケースも含める(`tests/services/test_daily_summary.py`と同型)

### Implementation for User Story 1

- [X] T006 [P] [US1] `src/polaris/agent/memory_housekeeping.py`を新規作成し、`HousekeepingSuggestionItem`/`HousekeepingDetectionResult`(BaseModel)、`MemoryHousekeepingDetector`(Protocol)、`build_memory_housekeeping_agent(settings)`、`AgentMemoryHousekeepingDetector`を実装する(`agent/memory_extract.py`のProtocol+Agentラッパー型を踏襲。`settings.llm.model_id`を使い、reasoningは無効化しない。`data-model.md`・`research.md` Decision 3/4参照)
- [X] T007 [US1] `src/polaris/services/memory_housekeeping.py`を新規作成し、`run_memory_housekeeping(*, detector, memory_repo, housekeeping_repo, settings)`を実装する。`MemoryRepository.list_themes()`でslug・`updated_at`一覧を取得し、各slugを`services/memory.read_theme_file(slug, settings=settings)`で読み、`(slug, 内容, updated_at)`をdetectorに渡し、結果を`MemoryHousekeepingSuggestion`行に変換して`replace_all`で保存する(T003・T006に依存。テーマ0件でも`replace_all([])`は必ず呼ぶ、`data-model.md`参照)
- [X] T008 [US1] `src/polaris/cli/run_memory_housekeeping.py`を新規作成する。`uv run python -m polaris.cli.run_memory_housekeeping`のエントリポイント。`api/app.py`とは別にEngine・Repository・Agentを自前で組み立てる(GPU不要、`QwenEmbedder`はロードしない)。対象期間引数は持たない(`research.md` Decision 6)。`cli/generate_daily_summary.py`と同型(T007に依存)

**Checkpoint**: CLIを実行すると記憶テーマの整理候補がDBに保存される、という中核機能がこの時点で単独動作する

---

## Phase 4: User Story 2 - 整理候補があることにチャット画面で気づける (Priority: P2)

**Goal**: 検出済みの候補がある場合、チャット画面を開くだけで通知(バナー)が表示される

**Independent Test**: `quickstart.md`シナリオ4(候補がある状態でチャット画面を開き、バナーに件数・種別・対象テーマ・理由が表示されることを目視確認。`GET /api/memory-housekeeping/latest`のレスポンス形も確認)

### Implementation for User Story 2

- [X] T009 [US2] `src/polaris/api/app.py`に`HousekeepingSuggestionResponse`/`MemoryHousekeepingResponse`(BaseModel)と`_memory_housekeeping_repo = MemoryHousekeepingRepository(_engine)`の構築、`GET /api/memory-housekeeping/latest`エンドポイントを追加する。`list_latest()`が空なら`None`を返す(`contracts/memory-housekeeping-api.md`参照。T003に依存)
- [X] T010 [US2] `frontend/src/MemoryHousekeepingBanner.tsx`を新規作成する。マウント時に`GET /api/memory-housekeeping/latest`を取得し、`suggestions`が1件以上あれば件数・各候補の種別(統合/分割/stale)・対象テーマ・理由が読めるバナーを表示する(`DailySummaryBanner.tsx`と同じ「コンポーネント内完結」パターン、取得失敗時は静かに諦める。この時点では既読管理は未実装でよい、US3で追加)
- [X] T011 [US2] `frontend/src/App.tsx`に`MemoryHousekeepingBanner`を差し込む(`DailySummaryBanner`と並べて`<main>`直後・composer手前、T010に依存)
- [X] T012 [P] [US2] `frontend/src/styles.css`に`.memory-housekeeping-banner`を追加する(`.daily-summary-banner`と近い見た目、アクセントカラーは区別する)

**Checkpoint**: 候補がある状態でチャット画面を開くと通知が表示される、という機能がこの時点で単独動作する

---

## Phase 5: User Story 3 - 一度確認した提案は繰り返し通知されない (Priority: P3)

**Goal**: 通知を閉じたら同じバッチの通知は再表示されず、新しいバッチ実行後は再び通知される

**Independent Test**: `quickstart.md`シナリオ5(通知を閉じてリロード→再表示されないこと。バッチ再実行後にリロード→新しい通知が表示されること)

### Implementation for User Story 3

- [X] T013 [US3] `frontend/src/MemoryHousekeepingBanner.tsx`に既読管理を追加する。`localStorage`キー`polaris.memoryHousekeeping.lastSeenGeneratedAt`に最終既読の`generated_at`を保持し、取得した`generated_at`が既読と一致すればバナーを表示しない。✕ボタンで`localStorage`に書き込んでから非表示にする(`DailySummaryBanner.tsx`の`LAST_SEEN_KEY`パターンと同型。`try/catch`で包む。T010に依存)

**Checkpoint**: 全User Storyが独立して動作する。閉じた通知が再表示されず、新しいバッチ後は再通知される

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 複数User Storyにまたがる仕上げ

- [X] T014 `uv run nox`(fix/typecheck/cspell/test)と`cd frontend && npx tsc -b`を実行し、クリーンであることを確認する
- [X] T015 `quickstart.md`の全シナリオ(1〜5)を手動E2Eで実施する
- [X] T016 [P] `specs/README.md`の024行を実装状況に応じて更新する(実装順リストからの除去含む、`023`の実装完了時の更新パターンを踏襲)
- [X] T017 [P] `specs/024-memory-theme-housekeeping/spec.draft.md`に実装状況・確定した未決定事項を追記する(`spec.md`のStatus行も合わせて更新)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 依存なし。すぐ着手可能
- **Foundational (Phase 2)**: Setup完了後。全User Storyをブロックする
- **User Stories (Phase 3+)**: いずれもFoundational完了後に着手可能
  - US1(Phase 3)はUS2/US3が読むデータを作る側のため、実質的にUS2/US3より先に完了させる必要がある(優先度どおりP1→P2→P3の順が自然)
- **Polish (Final Phase)**: 実施したい全User Story完了後

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完了後に着手可能。他Storyへの依存なし
- **User Story 2 (P2)**: Foundational完了後に着手可能(コードの依存はFoundationalの`MemoryHousekeepingRepository`のみ)。ただし検出結果が無いと動作確認できないため、実質的にUS1の後に検証する
- **User Story 3 (P3)**: US2が作成する`MemoryHousekeepingBanner.tsx`を拡張するため、US2完了後に着手する

### Within Each User Story

- テスト(US1)は実装前に書き、失敗することを確認する
- モデル/リポジトリ(Foundational)→エージェント→サービス→CLI/APIの順
- Story完了後に次の優先度へ進む

### Parallel Opportunities

- T004・T005(US1のテスト)は並行実行可能
- T006(エージェント)はT004・T005と並行実行可能(実装がテストの合否に影響しないファイルのため)
- T012(スタイル)はT009〜T011と並行実行可能
- T016・T017(ドキュメント更新)は並行実行可能

---

## Parallel Example: User Story 1

```bash
# US1のテストを並行して書く:
Task: "tests/db/test_memory_housekeeping_repository.py を新規作成"
Task: "tests/services/test_memory_housekeeping.py を新規作成"

# 検出エージェントは上記と並行で実装できる:
Task: "src/polaris/agent/memory_housekeeping.py を新規作成"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup完了
2. Phase 2: Foundational完了(CRITICAL — 全Storyをブロック)
3. Phase 3: User Story 1完了
4. **STOP and VALIDATE**: `quickstart.md`シナリオ1〜3でUser Story 1を単独検証
5. この時点でCLIを手動実行すれば検出結果がDBに貯まる状態(バナー表示はまだ無い)

### Incremental Delivery

1. Setup + Foundational → 土台完成
2. User Story 1追加 → 単独検証 → CLIでの検出が動く(MVP!)
3. User Story 2追加 → 単独検証 → チャット画面で通知が見える
4. User Story 3追加 → 単独検証 → 通知が繰り返されない
5. 各Storyが前のStoryを壊さずに価値を積み上げる

---

## Notes

- [P]タスク = 別ファイル、依存無し
- [Story]ラベルはUser Storyへのトレーサビリティ用
- 各User Storyは独立して完了・検証可能であるべき
- 実装前にテストが失敗することを確認する
- タスクごと、または論理的なまとまりごとにコミットする
- 各チェックポイントで立ち止まり、Storyの独立動作を検証してよい
