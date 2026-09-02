# Quickstart: 記憶テーマの定期棚卸し(memory-theme-housekeeping)動作検証

実装(`/speckit-tasks` → `/speckit-implement`後)が終わった時点で、この手順で一気通貫の動作を
確認する。`023-daily-summary-notification`の手動E2E検証と同じ形式。バッチ処理はCLIから手動実行する
(実際のcron登録は運用作業、spec Assumptions参照)。

## 前提

- バックエンド(`uv run uvicorn polaris.api.app:app --reload --reload-dir src --host 0.0.0.0 --port 8000`)と
  フロントエンド(`cd frontend && npm run dev`)が起動していること(README.md参照)
- `uv run nox`(fix/typecheck/cspell/test)がクリーンであること
- 記憶テーマが数件存在すること(無ければチャットで雑談し、017の抽出機構で数テーマ作っておく)

## シナリオ1: 内容が重複する記憶テーマが統合候補として検出される(P1)

1. `data/memory/`配下に、内容が明らかに重複する2つのテーマファイルを用意する(既存テーマを
   `cp`で複製し、`MemoryRepository.upsert_theme`相当を`sqlite3`で流すか、チャットで似た内容を
   2テーマ分作らせる)
2. `uv run python -m polaris.cli.run_memory_housekeeping`を実行する
3. `sqlite3 data/polaris.db "select suggestion_type, target_themes, detail from memory_housekeeping_suggestions;"`
   で、`merge`種別の行が1件でき、対象テーマ2件のslugと具体的な理由が入っていることを確認する

**期待結果**: `memory_housekeeping_suggestions`テーブルに統合候補が1行、理由の説明が具体的

## シナリオ2: テーマ0〜1件でもエラーにならない(P1、Edge Case)

1. テストDB(`data/polaris.db`のコピー等、`memory_theme`テーブルを一時的に空にした状態)に対して
   `uv run python -m polaris.cli.run_memory_housekeeping`を実行する
2. コマンドが正常終了(非0の終了コードにならない)し、ログに「候補0件」の旨が出ることを確認する

**期待結果**: エラーで落ちない。`memory_housekeeping_suggestions`は空のまま(または既存行があれば消去される)

## シナリオ3: バッチ再実行で前回の候補が完全に置き換わる(P1)

1. シナリオ1の状態から、片方のテーマファイルを直接編集して重複を解消する
2. `uv run python -m polaris.cli.run_memory_housekeeping`を再実行する
3. `sqlite3 data/polaris.db "select count(*) from memory_housekeeping_suggestions;"`で、
   件数がシナリオ1時点から変化している(重複が解消されていれば0件になる)ことを確認する

**期待結果**: 過去の検出結果が蓄積されず、常に最新バッチの内容のみが残っている
(`contracts/memory-housekeeping-api.md`・`data-model.md`のFR-005参照)

## シナリオ4: チャット画面で通知バナーが表示される(P2)

1. シナリオ1(候補が1件以上ある状態)の直後にブラウザでチャット画面を開く
2. 画面上に整理候補の通知(バナー)が表示され、候補の件数・種別・対象テーマ・理由が読めることを
   目視確認する
3. `curl localhost:8000/api/memory-housekeeping/latest`で`contracts/memory-housekeeping-api.md`の
   レスポンス形と一致するJSONが返ることを確認する

**期待結果**: バナーに検出内容が具体的に表示される。候補が0件の状態(シナリオ2の後)で開くと
バナー自体が表示されない(FR-008)

## シナリオ5: 一度閉じた通知は再表示されず、新しいバッチ後は再表示される(P3)

1. シナリオ4のバナーを✕で閉じる
2. ページをリロードし、同じ内容の通知が再表示されないことを確認する
3. `uv run python -m polaris.cli.run_memory_housekeeping`を(内容を変えずに)再実行し、
   再度ページをリロードして、`generated_at`が更新された新しい通知が表示されることを確認する
   (内容が同一でも再通知されうる、Edge Cases参照)

**期待結果**: 既読状態はブラウザのlocalStorageに保持され、新しいバッチ実行のたびにリセットされる
