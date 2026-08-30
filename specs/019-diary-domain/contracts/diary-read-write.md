# Contract: バックフィル書き込み・期間読み取り・執筆中パネル(User Story 4-6)

`contracts/state.md`(AG-UI state)とは別に、User Story 4-6で追加するインターフェースをまとめる。

## 書き込み: `record_diary_turn`への`target_date`追加

内部関数のシグネチャ変更(外部公開インターフェースではない)。`data-model.md`参照。呼び出し元
(`api/app.py`の`_record_diary_task`)は、新規の軽量エージェント`DiaryDateInferrer`
(`agent/diary_date_infer.py`)で会話文面から過去日を推定し、推定できた場合にのみ`target_date`を渡す。
メインのチャットエージェント(`chat_agent.py`)には手を加えない — 日記の記録処理自体がtool呼び出し
ではなくバックグラウンド処理(Decision 1)であるため、日付推定も同じ後処理段の軽量LLM呼び出しとして
行う(research.md Decision 7)。

## 読み取りtool: `get_diary_range(start_date, end_date)`

チャットエージェントのtoolとして`chat_agent.py`に登録する(`data-model.md`のシグネチャ参照)。

- **入力**: `start_date: date`, `end_date: date`(単日は同じ値)
- **出力(正常時)**: `DiaryRangeResult`(該当期間に実在するエントリのみ、日付昇順)
- **出力(期間超過時)**: 62日を超える範囲を指定された場合、`get_paper_full_text`の0件/複数件時と
  同様に日本語の案内メッセージ文字列を返す(例:「指定期間が広すぎます(62日以内にしてください)」)。
  例外は送出しない(他の全文系toolと同じ「LLMに次の一手を示す」設計)
- **副作用**: 無し(読み取り専用)
- **ADR-0012登録**: `services/history_trim.py`の`FULL_TEXT_TOOL_NAMES`に`"get_diary_range"`を
  追加する。複数回呼ばれた場合、履歴上最新の結果のみを残し、古い結果は`<omitted ...>`に置換される
  (`get_paper_full_text`と同じ挙動)

## 読み取りAPI: `GET /api/diary/recent`

執筆中パネル(User Story 6)専用の読み取り専用エンドポイント。`GET /api/daily-summary/latest`と
同じ「フロントがページ内で能動的に叩く、チャットのAG-UIストリームとは独立したエンドポイント」パターン。

- **リクエスト**: `GET /api/diary/recent?count=3`(`count`省略時は3)
- **レスポンス**: `DiaryDayResponse`(`entry_date`/`content`/`updated_at`)の配列。`entry_date`昇順
  (古い日が先頭)で、**末尾の要素が常にアンカー**(`updated_at`が最新のエントリ)。アンカーを
  明示するフィールドは持たせず、フロント側は「最後の要素を強調表示する」だけで済むようにした。
  記録が1件も無ければ空配列を返す
- **既読管理**: 無し(023の日次サマリーと違い、これは「見るたびに最新化される」パネルであり
  read/unread概念を持たない)
- **呼び出しタイミング**: フロントは日記モードでのターン完了後に叩き直す(`research.md` Decision 9の
  「表示トリガー」参照)。ページロード時の自動フェッチは行わない(日記モードに入っていない限り
  パネル自体を表示しないため)
