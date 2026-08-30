# Implementation Plan: 日記ドメイン(diary-domain)

**Branch**: `019-diary-domain` | **Date**: 2026-08-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/019-diary-domain/spec.md`

## Summary

チャット入力欄の「日記モード」トグルをONにしている間の会話内容を、日付ごとに1件のエントリへ
自動的にまとめて記録する。技術的には`017-chat-memory`のログ層(`DiaryEvent`、追記のみ)+
現在状態層(`DiaryRecord.content`、LLMによる読み直し)パターンを、テーマ分類・記憶選別ステップを
省いた簡略版として再利用する。モードの管理は`015-paper-qa-chat`のAG-UI state機構を汎用化
(`PaperModeState` → `ChatUIState`)して行う。詳細な決定根拠は`research.md`参照。

## Technical Context

**Language/Version**: Python 3.14(`pyproject.toml`の`requires-python`)、フロントエンドはTypeScript
(Vite + React)

**Primary Dependencies**: Pydantic AI v2(`build_model`経由でOpenRouter接続)、FastAPI、SQLModel、
AG-UI(`pydantic_ai.ui.ag_ui.AGUIAdapter` + `@ag-ui/client`の`HttpAgent`)。新規の外部ライブラリ追加は無し

**Storage**: 既存のSQLiteファイル(`data/polaris.db`)に`diary_records`/`diary_events`テーブルを追加。
ファイルストレージ(`memory/<slug>.md`のような形)は使わない(`research.md` Decision 2)

**Testing**: `pytest`(`uv run nox`のtestセッション)、`tests/db/`・`tests/services/`に既存パターンで
追加。フロントエンドは`npx tsc -b`(型チェックのみ、既存にE2Eテストフレームワークは無い、Playwright MCP
経由の手動確認が既存の慣例)

**Target Platform**: `localhost`、単一ユーザー、認証なし(憲章のScope Constraints)

**Project Type**: Web service(既存の`src/polaris/` + `frontend/`構成に機能追加。新規プロジェクト構造は
不要)

**Performance Goals**: 個人用ツールのため定量目標なし。既存の`ChatSettings`/`MemorySettings`と
同水準(チャット1ターンあたりLLM呼び出し1〜2回程度)を維持する

**Constraints**: ADR-0005(AG-UIステートレス設計、サーバーは会話履歴を保持しない)に従う。017の記憶抽出は
`asyncio.create_task`のfire-and-forgetパターン(`_extract_memory_task`)を踏襲する。日記の記録
(`_record_diary_task`)は当初同じfire-and-forgetを踏襲したが、User Story 6(執筆中パネル)追加時に
「ターン完了直後にパネルを取り直す」設計とレースコンディションを起こすと判明したため`on_complete`内で
直接`await`する方式に変更した(`research.md`の該当Decisionの「実装時の訂正」参照)

**Scale/Scope**: 単一ユーザーの日次利用。1日あたりのエントリ数は多くても数件(複数回モードに出入り
しても1エントリに集約されるため、スケールの懸念は無い)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 評価 |
|---|---|
| I. Python + Pydantic AI | PASS — `DiaryRecord`/`DiaryEvent`はSQLModel、rewriterは`pydantic_ai.Agent`で実装する |
| II. YAGNI(個人用ツール) | PASS — 想起機能・一覧UI・記憶選別ステップをすべてv1スコープ外にし、DBカラムのみで完結させた(`research.md` Decision 2/3) |
| III. モデル選択は設定値のみ | PASS — rewriterは`build_model(settings)`(`settings.llm.model_id`)を使う。新規設定は追加しない(Decision 6) |
| IV. Hub/Satelliteパターン | PASS — `Item`(hub)+`DiaryRecord`(satellite)、`spec.draft.md`が最初から決めていた設計を踏襲 |
| V. AG-UIチャットプロトコル | PASS — 状態管理は既存の`RunAgentInput.state`⇄`StateSnapshotEvent`機構をそのまま使う。新規APIエンドポイントは追加しない |
| Scope Constraints(localhost/単一ユーザー/認証なし) | PASS — 変更なし |
| Development Workflow(walking skeleton) | PASS — P1(記録)→P2(重複防止)→P3(UI表示)の順で独立にテスト可能なユーザーストーリーに分割済み(`spec.md`) |

違反なし。Complexity Trackingへの記載は不要。

*Phase 1設計(data-model.md/contracts/)を反映して再評価: 上記の判断に変更なし。`PaperModeState`→
`ChatUIState`の改名は原則Vの「既存機構の再利用」をむしろ徹底する方向の変更であり、新たな懸念は無い。*

## Project Structure

### Documentation (this feature)

```text
specs/019-diary-domain/
├── spec.draft.md         # 当初の下書き(たたき台、参考情報として残す)
├── spec.md               # /speckit-specify command output
├── plan.md                # This file (/speckit-plan command output)
├── research.md            # Phase 0 output
├── data-model.md          # Phase 1 output
├── contracts/
│   └── state.md           # Phase 1 output(AG-UI state の契約)
├── quickstart.md           # Phase 1 output
├── checklists/
│   └── requirements.md
└── tasks.md                # Phase 2 output (/speckit-tasks command - NOT created here)
```

### Source Code (repository root)

既存の単一プロジェクト構成にそのまま追加する(新規オプション不要)。

```text
src/polaris/
├── domain/entities.py              # ItemType.diary 追加、DiaryRecord/DiaryEvent 追加
├── db/diary_repository.py          # 新規: DiaryRepository
├── agent/diary_rewrite.py          # 新規: Protocol + Agentラッパー(017のmemory_extract.pyのrewrite部分と同型)
├── agent/chat_agent.py             # PaperModeState → ChatUIState 改名 + diary_mode フィールド追加
├── services/diary.py               # 新規: append_event/rewrite のオーケストレーション(017のservices/memory.pyと同型)
└── api/app.py                      # _diary_repo 追加、on_complete に _extract_diary_task 追加(017の_extract_memory_taskと並列)

frontend/src/
├── useChatAgent.ts                 # PaperModeState → ChatUIState 型改名 + diary_mode フィールド追加
└── App.tsx                         # 日記モードトグルボタン・モードチップ表示を追加

tests/
├── db/test_diary_repository.py     # 新規
└── services/test_diary.py          # 新規(フェイクrewriter + 実DBパターン、017のtest_memory.pyと同型)
```

**Structure Decision**: 新規ディレクトリ・新規プロジェクトは作らない。既存の`src/polaris/{domain,db,agent,services,api}`
+ `frontend/src/`の各層に1〜2ファイルずつ追加し、017/015が確立した既存パターンをそのまま踏襲する。

## Complexity Tracking

*(Constitution Checkに違反なし、記載事項なし)*

## Increment: User Story 4-6(バックフィル・期間読み取り・執筆中パネル、2026-08-30追記)

`spec.draft.md`「v1後の検討メモ」を正式化した追加分。上記のTechnical Context/Constitution Checkは
変更なし(新規依存ライブラリ・新規プロジェクト構造なし)。追加で触るファイルのみ列挙する。

```text
src/polaris/
├── agent/diary_date_infer.py       # 新規: DiaryDateInferrer(Protocol) + Agentラッパー(US4)
├── services/diary.py               # record_diary_turn に target_date 引数を追加(US4)
├── db/diary_repository.py          # list_records_in_range/get_latest_updated_record/
│                                     # list_records_before を追加(US5/US6)
├── agent/chat_agent.py             # get_diary_range tool を追加(US5)。日付推定はchat_agent.pyの
│                                     # 外側(_record_diary_task)で行うため、_INSTRUCTIONSへの追記は無い
├── services/history_trim.py        # FULL_TEXT_TOOL_NAMES に "get_diary_range" を追加(US5、ADR-0012対応)
└── api/app.py                      # _record_diary_task が DiaryDateInferrer を呼んでから
                                      # record_diary_turn に target_date を渡す(US4)。
                                      # GET /api/diary/recent を追加(US6)

frontend/src/
├── useChatAgent.ts                 # /api/diary/recent を叩くフック追加(US6)
├── App.tsx                         # 執筆中パネルの表示・折りたたみ(US6)
└── styles.css                      # パネル用CSS(US6)

tests/
├── db/test_diary_repository.py     # 追加: list_records_in_range/get_latest_updated_record/list_records_before
└── services/test_diary.py          # 追加: target_date指定時の挙動(US4、DiaryDateInferrerはフェイクに差し替え)
```

`agent/diary_date_infer.py`自体(実LLM呼び出しのAgentラッパー)は、既存の`agent/*.py`と同じ慣例で
専用テストを持たない(オーケストレーション層をフェイクProtocol経由でテストする方針、`plan.md`の
テスト方針参照)。

**Constitution Check(再評価)**: 引き続き全項目PASS。`get_diary_range`はHub/Satelliteパターン
(原則IV)に沿った既存`DiaryRecord`への読み取りのみで新規テーブルを増やさない。62日の上限ガードは
YAGNI(原則II)というより既存のコンテキスト肥大化対策(ADR-0012)の踏襲であり、新たな複雑さの
持ち込みではない。
