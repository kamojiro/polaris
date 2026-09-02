# Implementation Plan: 記憶テーマの定期棚卸し(memory-theme-housekeeping)

**Branch**: `024-memory-theme-housekeeping` | **Date**: 2026-09-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/024-memory-theme-housekeeping/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

017-chat-memoryの記憶テーマ(`memory/<slug>.md`)を対象に、統合・分割・stale候補を検出する読み取り専用のバッチ処理を追加する。`023-daily-summary-notification`が確立した「OS cronから独立CLIを叩く→DBに保存→フロントが取得しバナー表示→既読管理はlocalStorage」というパターンをそのまま踏襲するが、023と異なり実行頻度は週1回を想定し、対象期間による絞り込みは行わず(常に「今この瞬間の全テーマの現在の内容」を評価)、出力も単一の文章ではなく構造化された提案のリスト(0〜N件)になる。v1では検出・表示のみで、提案の自動/手動適用は行わない(017に再編ツール自体が無いため)。

## Technical Context

**Language/Version**: Python 3.14(既存プロジェクトと同一)

**Primary Dependencies**: pydantic-ai v2(構造化出力エージェント)、FastAPI、SQLModel、React 19 + TypeScript(フロント)

**Storage**: SQLite(既存の`create_db_engine`が返す`Engine`を共有。新規テーブル`memory_housekeeping_suggestions`を1つ追加)

**Testing**: pytest。集計・検出ロジックはフェイクの`HousekeepingDetector`実装 + 実SQLite(tmp)の組み合わせ(`tests/services/test_daily_summary.py`と同じパターン)。実LLM呼び出しを伴う検証が要る場合は`llm`マーカー(`uv run nox -s test_llm`)を使う(019で確立済みのパターン)

**Target Platform**: Linux server(localhost、単一ユーザー)

**Project Type**: 既存のweb-service(FastAPIバックエンド + Reactフロントエンド)への機能追加

**Performance Goals**: 該当なし(チャットのターンをブロックしない独立バックグラウンドバッチ。実行時間の上限要件は無い)

**Constraints**: バッチ処理はチャットの応答生成(ADR-0003の3段パイプライン)と完全に独立していなければならない(FR-004)。記憶テーマファイル(`memory/<slug>.md`)・`MemoryEvent`ログを一切書き換えてはならない(v1は検出・表示のみ)

**Scale/Scope**: 記憶テーマ数は現状十数件程度(埋め込み類似度のような専用インフラが不要という判断の根拠、spec Assumptions参照)。想定実行頻度は週1回(spec Assumptions参照、コード側に頻度パラメータは持たない)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Python + Pydantic AI**: 検出結果は`BaseModel`(`HousekeepingSuggestionItem`のリスト)、永続化は`SQLModel`(`MemoryHousekeepingSuggestion`)。素のdictは使わない。✅
- **II. YAGNI for a Single-User Tool**: 検出精度はLLM任せ(埋め込み類似度基盤を新設しない)、per-suggestion既読APIやdismissフラグを持たない(023と同じlocalStorage方式)。✅
- **III. Model Selection via Settings Only**: 検出用エージェントのモデルは`settings.llm.model_id`(メインモデル)を使う。テーマ群を横断して判断する必要があり017の想起用軽量モデル(`recall_model_id`)には荷が重いと判断(023の日次サマリーと同じ判断軸)。設定値経由でのみモデルを選ぶ(コードにハードコードしない)。✅
- **IV. Hub/Satellite Data Pattern**: `MemoryHousekeepingSuggestion`は`MemoryTheme`/`DailySummaryRecord`と同じく`Item`ハブを経由しない横断的データ(特定の知識アイテム1件に紐づかないため)。既存の非Hub系テーブルと同じ扱い。✅
- **V. AG-UI Chat Protocol**: 本機能はチャットのターンに一切関与しない(通知バナーの表示のみ)。AG-UIプロトコル自体への変更は無い。✅

違反なし。Complexity Trackingへの記載は不要。

**Post-Design再チェック**(Phase 1完了後): `data-model.md`確定後も上記5項目に変化なし。
`MemoryHousekeepingSuggestion`は既存の非Hub系テーブル(`MemoryTheme`/`DailySummaryRecord`)と
同じ形に収まり、新規の抽象化(DIコンテナ・専用フレームワーク等)は導入していない。✅

## Project Structure

### Documentation (this feature)

```text
specs/024-memory-theme-housekeeping/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/polaris/
├── domain/entities.py                           # MemoryHousekeepingSuggestion(SQLModel)
├── db/
│   └── memory_housekeeping_repository.py        # 新規: replace_all / list_latest
├── agent/
│   └── memory_housekeeping.py                   # 新規: Protocol + Agentラッパー(構造化出力)
├── services/
│   └── memory_housekeeping.py                   # 新規: 全テーマ読み込み→検出→保存のオーケストレーション
├── cli/
│   └── run_memory_housekeeping.py               # 新規: CLIエントリポイント(cronから叩く)
└── api/app.py                                   # GET /api/memory-housekeeping/latest 追加

frontend/src/
├── MemoryHousekeepingBanner.tsx                 # 新規: DailySummaryBanner.tsxと同型
├── App.tsx                                       # バナーを1行差し込む
└── styles.css                                    # .memory-housekeeping-banner

tests/
├── db/test_memory_housekeeping_repository.py    # 新規: replace_all(全置き換え)/list_latest
└── services/test_memory_housekeeping.py         # 新規: 検出オーケストレーション(フェイクDetector)
```

**Structure Decision**: 既存の単一プロジェクト構成(`src/polaris/` + `frontend/`)をそのまま使う。`023-daily-summary-notification`が確立したレイヤー構成(settings → domain entity → repository → agent → service → CLI → API → frontend banner)を1対1で踏襲するため、新規オプション構造の検討は不要。

## Complexity Tracking

*違反なし、記載事項なし。*
