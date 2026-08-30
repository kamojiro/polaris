# Quickstart: 日記ドメイン(diary-domain)動作検証

実装(`/speckit-tasks` → `/speckit-implement`後)が終わった時点で、この手順で一気通貫の動作を
確認する。`023-daily-summary-notification`の手動E2E検証と同じ形式。

## 前提

- バックエンド(`uv run uvicorn polaris.api.app:app --reload --reload-dir src --host 0.0.0.0 --port 8000`)と
  フロントエンド(`cd frontend && npm run dev`)が起動していること(README.md参照)
- `uv run nox`(fix/typecheck/cspell/test)がクリーンであること

## シナリオ1: 日記モードで会話するとエントリが記録される(P1)

1. ブラウザでチャット画面を開く
2. 入力欄のツールバーから日記モードをONにする
3. 「今日は散歩に行って、いい天気だった」と送信する
4. `sqlite3 data/polaris.db "select entry_date, content from diary_records;"`で、今日の日付の
   エントリが1件でき、散歩の内容が反映されていることを確認する

**期待結果**: `diary_records`テーブルに1行、`content`に散歩の話が含まれる

## シナリオ2: 同じ日に何度もモードへ出入りしても1エントリに保たれる(P2)

1. シナリオ1の続きで、日記モードをOFFにする
2. 別の話題(例: 保存済み論文の質問)を1往復する
3. 再び日記モードをONにし、「夕方には雨が降った」と送信する
4. `sqlite3 data/polaris.db "select count(*) from diary_records where entry_date = date('now');"`が
   `1`のままであることを確認する
5. `content`に散歩の話と雨の話の両方が(1つの自然な文章として)反映されていることを確認する

**期待結果**: エントリは増えず1件のまま、内容は両方のやり取りを踏まえて更新されている

## シナリオ3: モード表示が画面で判別できる(P3)

1. 日記モードをONにし、画面上に日記モード中であることを示す表示が現れることを目視確認する
2. OFFにすると表示が消えることを確認する
3. 論文モード(既存機能)と日記モードを同時にONにし、両方の表示が同時に出ることを確認する
   (015・019は排他ではない、FR-006)

**期待結果**: モードの状態が常に画面から読み取れる。両モードが独立して共存する

## 回帰確認

- `uv run nox`が引き続きクリーンであること
- 日記モードを一切使わない既存のシナリオ(論文の保存・TODO・ニュース一覧)が今までどおり動くこと
  (`ChatUIState`への改名がAPIレスポンスの形自体を変えていないことの確認)
