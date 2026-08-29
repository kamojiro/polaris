# 0012. 会話履歴中の古い巨大ToolReturnPartを、ターン完了時にMESSAGES_SNAPSHOTで置き換える

## ステータス

採択

## コンテキスト

ADR-0005(AG-UI直接接続)の設計どおり、サーバーはステートレスで会話履歴を一切保持しない。フロントの`HttpAgent`(`@ag-ui/client`)がブラウザ側で`agent.messages`(user/assistant/tool全メッセージ)を保持し、`POST /api/chat`のたびに`RunAgentInput.messages`として全履歴を毎回まるごと送り返す。`App.tsx`の画面描画は`role === "user" || role === "assistant"`のみをフィルタして表示するため(`tool`ロールのメッセージは非表示)、ユーザーの目に見える会話の長さと、実際にLLMへ送られるトークン量は一致しない。

`015-paper-qa-chat`(ADR-0009)は`get_paper_full_text`で論文の抽出済み全文をそのまま会話に取り込む設計にした。実測で1論文151k文字≒58,647トークン(ADR-0009)。この`ToolReturnPart`は一度会話に乗ると、以後の全ターンで無条件に再送され続ける。1論文に集中する短い会話では問題にならないが、同じセッション内で複数論文を順に読む、同じ論文に離脱→再突入して全文が重複する、といったケースでコスト・レイテンシが単調に悪化する。将来`013-ir-analysis-domain`が同種の全文取得toolを持つと同じ問題がドメイン横断で悪化する。

## 決定

`get_paper_full_text`のような「対象を切り替えながら全文を取り込む」toolについて、**履歴内で一番新しいToolReturnPart 1件だけを残し、それより古いものは全て短いプレースホルダに置換する**。

判定にitem_idや`active_paper`との照合は使わない。`ToolCallPart`/`ToolReturnPart`が元々持っている`tool_name`と、メッセージ列内での出現順序だけで十分に判定できる(同じtoolの中で一番新しいものだけが「今使われている」もの、という単純な時系列ルール)。

プレースホルダは`<omitted ...>`タグで囲み、本文ではなくメタ情報であることをモデルに示す。中身は元の`ToolCallPart`の引数(モデルが渡した検索クエリ文字列)をそのまま使えば十分で、item_idの復元・DB再検索・本文への隠しマーカー埋め込みは不要:

```
<omitted tool="get_paper_full_text" query="attention is all you need">全文は省略されました。必要なら再度get_paper_full_textを呼び出してください。</omitted>
```

この加工は`/api/chat`の`on_complete`(`api/app.py`、そのターンの`result.all_messages()`に既にアクセスできる箇所)で行い、加工済みの全メッセージ列をAG-UIの`MessagesSnapshotEvent`(`ag_ui.core`、`StateSnapshotEvent`と同じ「スナップショット系」イベント)として`yield`する。クライアント(`HttpAgent`)はこれを受け取ると`agent.messages`を丸ごと置き換える想定(`STATE_SNAPSHOT`が`state`を上書きするのと同じ挙動のはず、実装時に実機で確認する)。

これにより、次のターン以降はクライアント自身が保持する履歴が既に軽い状態になっているため、サーバー側で毎ターン履歴をスキャン・加工し直す必要がない。ブラウザ→サーバーの生のHTTP転送量自体も、この時点から実際に小さくなる(後述、当初案からの改善点)。

`get_paper_full_text`はLLM呼び出しを伴わない冪等な処理(`PaperRecord.pdf_path`からのpypdf再抽出)のため、古い論文について再度質問された場合にツールが呼び直されるコストは小さい。情報は失われず(DBに実体が残っている)、埋め込み検索(ADR-0011で一時停止済み)を復活させる必要もない。

## 検討した代替案

- **受信時(前処理)にトリミングする**: `ADR-0003`の前処理段で、毎ターン受信した履歴を`active_paper.item_id`と照合してトリミングする案を先に検討したが、(1) 毎ターン同じ判定をやり直す無駄があり、(2) クライアント側の保持データ自体は汚れたままなので、ブラウザ→サーバーの転送量そのものは減らせない、という2点で今回の方式に劣る。ターン完了時に1回だけ書き換えて突き返す方が、判定に必要な情報(完了時点の履歴・状態)が揃うタイミングとも一致し、以後の全ターンに効果が波及する
- **item_idで`active_paper`と照合する**: 当初、置換対象を「現在の`active_paper.item_id`と一致するかどうか」で判定しようとしたが、item_idを`ToolReturnPart`の本文やtool呼び出し引数から復元する手間(DB再検索、または本文への隠しマーカー埋め込み)が発生する。「履歴内で一番新しいものだけ残す」という時系列だけのルールでも同じ結果(論文切り替え・重複読み込みのどちらも正しく処理される)が得られるため、不要な複雑さと判断した
- 古い`ToolReturnPart`をLLMで要約してから残す: 追加LLM呼び出しが必要になる。`get_paper_full_text`の再呼び出しはLLM不要でほぼ無料なため、要約よりプレースホルダ+再取得の方が単純で正確
- 埋め込み検索(vec0)を復活させ、全文の代わりに関連チャンクだけ渡す: ADR-0009が明示的に避けた設計(チャンク化特有の精度問題)に逆戻りするため不採用
- サーバーをステートフル化し、セッションIDで正本の履歴を持つ: 今回の方式で転送量問題も併せて解決できる見込みのため、優先度を下げる

## 結果(Consequences)

良い面: LLMへの入力トークン量が頭打ちになる。画面上のユーザー体験には変化がない。`MessagesSnapshotEvent`でクライアント側の保持データ自体を書き換えるため、ブラウザ→サーバーの転送量も実際に減る(前バージョンのADR案では「LLMのトークン量は減るが転送量自体は変わらない」としていたが、この設計変更で解消された)。判定ロジックがitem_id照合を必要とせず単純(tool_nameと出現順序だけ)。

悪い面: 過去に読んだ論文について再度質問されると、`get_paper_full_text`が再度呼ばれる分だけ体感レイテンシが増える(実測は未計測)。トリミング対象を`get_paper_full_text`のような「同じtoolで対象を切り替えながら呼ばれる」toolに限定しており、`web_fetch`/`web_search`のように毎回対象(URL/クエリ)が変わり得るが「今アクティブな1件」という概念が無いtoolには同じ単純ルール(最新1件だけ残す)は使いにくく、別途ターン数/文字数ベースの閾値が必要(未設計)。

### 実装(2026-08-30)

- トリミングの純ロジックは`src/polaris/services/history_trim.py`の`trim_stale_full_text_results()`に実装した。対象tool名は`FULL_TEXT_TOOL_NAMES: frozenset[str]`定数(現状`{"get_paper_full_text"}`)で、将来`013-ir-analysis-domain`の`get_ir_full_text`等を追加する場合はこの定数に足すだけでよい。`AgentRunResult.all_messages()`を受け取り、元のリスト・メッセージ・パートは一切変更せず(`dataclasses.replace`でトリム対象メッセージのみ新規オブジェクトを作る)、新しいリストを返す。
- `src/polaris/api/app.py`の`/api/chat`の`on_complete`から`_emit_trimmed_history_event()`を呼び、`trim_stale_full_text_results(result.all_messages())`の結果を`pydantic_ai.ui.ag_ui.AGUIAdapter.dump_messages()`(pydantic-ai本体がAG-UIアダプタの`load_messages`と対で持つ、`ModelMessage`列→AG-UI wireメッセージ列の変換関数)に通し、`MessagesSnapshotEvent(messages=...)`として`yield`している。ハンドロールした変換ロジックは追加していない。
- `HttpAgent`(`@ag-ui/client`)の`MESSAGES_SNAPSHOT`ハンドラを`frontend/node_modules/@ag-ui/client/dist/index.mjs`で確認した: 保持中の`agent.messages`をイベントの`messages`とメッセージIDで突き合わせ、IDが一致しない既存メッセージ(activity/reasoning以外)は破棄し、新しいメッセージで置き換える実装だった。`dump_messages()`はメッセージ変換のたびに新規UUIDを振るため、既存メッセージとID一致することは無く、実質的に「保持中の全メッセージを新しいスナップショットで丸ごと置換」という動作になることを実機コード読解で確認済み(このチャットは活用していないactivity/reasoningロールを除けば完全な置換)。ブラウザでのライブLLM経由の実地確認(2論文を読んで3ターン目のPOSTボディを見る)は、このサンドボックスにOpenRouterのAPIキー・GPU embedderが無いため実施できなかった。代わりに`trim_stale_full_text_results()` → `AGUIAdapter.dump_messages()` → `MessagesSnapshotEvent`のパイプライン全体を、LLM呼び出し無しで手動スクリプト実行して確認した(50,000文字の古いToolReturnPartが103文字のプレースホルダに縮み、最新分は無傷で残ることを確認)。
- ユニットテストは`tests/services/test_history_trim.py`(2論文を順に読む履歴・list_papers呼び出しを混ぜた履歴に対し、古い方のみプレースホルダ化されること、無関係なtoolは触られないこと、元のオブジェクトが変更されないこと、対象toolが1度も呼ばれない履歴はno-opであることを検証)。`uv run nox`(fix/typecheck/cspell/test)は全てクリーン。

## 関連

- 関連spec: `specs/015-paper-qa-chat`(`get_paper_full_text`/`active_paper`)、`specs/013-ir-analysis-domain`(将来同種の対応が必要になる想定)
- 関連ADR: ADR-0003(パイプラインとしての位置づけ)、ADR-0005(ステートレス設計、転送量減少はこの決定で部分的に補われる)、ADR-0009(全文インコンテキスト方式、実測コスト)、ADR-0011(embedding一時停止との整合)
