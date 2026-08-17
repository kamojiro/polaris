# 005. Eval harness(pydantic_evals)

## ステータス

未着手

## 概要

pydantic_evals(`Dataset`/`Case`/`Evaluator`)を土台に、次の6指標を測定する仕組みを作る: スキーマ妥当性率・tool call選択精度・リトライ発生率・レイテンシ(p50/p95)・コスト・世代差分。dev(Qwen3-30B-A3B)/prod(Qwen3.6-35B-A3B)の比較や、モデル世代交代時の改善幅の可視化に使う。設計自体は`wishlist/wishlist-design.md` 7章でかなり詳細化済みで、本specはそれを実装可能な粒度に落とす。

## 対象にする実データ

今の実装(001〜004)で実際にLLM呼び出しが発生している箇所は2つ。v1のDatasetはこの2つを対象にする。

1. **論文Ingestの構造化抽出**(`002-papers-ingest-full`のStructureフェーズ): PDF/abstractのテキストからPaperRecordの欠落フィールド・要約を生成する呼び出し。スキーマ妥当性率・リトライ発生率の主な測定対象。
2. **チャットエージェントのtool呼び出し**(`001-walking-skeleton`/`003-chat-ui-polish`): 「このarXivのURLを保存して」「論文の一覧を見せて」のような自然文からのtool選択。tool call選択精度の測定対象。

レイテンシ・コストはこの2つのどちらの呼び出しでも共通して測定する。

## ディレクトリ構成(案)

```
evals/
  datasets/
    paper_structure.yaml     # 構造化抽出用のCase集(inputs=生テキスト, expected_output=PaperRecord)
    chat_tool_calls.yaml     # tool呼び出し用のCase集(inputs=自然文, metadata.expected_tool_calls)
  evaluators.py               # custom Evaluator定義
  run_monthly.py              # 月次実行スクリプト
  results/
    qwen3-30b-a3b_2026-08.json
    qwen3.6-35b-a3b_2026-08.json
```

## 各指標の実装方針

| 指標 | 実装方針 |
|---|---|
| スキーマ妥当性率 | `retries=0`に固定した専用エージェント(通常運用のagentとは別インスタンス)で一発勝負させ、`PaperRecord.model_validate()`を試すcustom Evaluator。通常のretries設定のまま測ると「最終的にはほぼ100%成功」になり意味を失う点に注意 |
| tool call選択精度 | `run.all_messages()`から実際のtool callを抽出し、`Case.metadata["expected_tool_calls"]`と緩い構造比較(tool名の完全一致+引数はキーの部分一致・型一致)を行うcustom Evaluator |
| リトライ発生率 | 近似値として`run.usage().requests - 1`。正確に測るなら`logfire.instrument_pydantic_ai()`を有効化しspanから集計(v1では近似値で十分) |
| レイテンシ(p50/p95) | 各Caseの実行時間を`time.perf_counter`で計測しmetadataに記録、全Case終了後に一度だけ走るreport evaluatorでpercentileを算出 |
| コスト | `run.usage().cost`(pydantic-ai v2が`genai-prices`で自動算出)を使う。無料モデル(dev)は`cost=0`になるはず |
| 世代差分 | `Dataset.evaluate()`の結果(`EvaluationReport`)を`evals/results/<model>_<YYYY-MM>.json`に保存し、前回分との差分を取る比較スクリプトを自作(pydantic_evalsに標準の自動diff機能があるかは未確認のため) |

## 実行フロー

1. 月次スケジュールタスクとして`run_monthly.py`を実行
2. dev(Qwen3-30B-A3B)・prod(Qwen3.6-35B-A3B)の両方で同一Datasetを評価。prodは有償なので、頻度は月次程度に抑える(devはより高頻度に回してよい)
3. 結果を`evals/results/<model>_<YYYY-MM>.json`に保存
4. 前月/前バージョンとの差分レポートを生成

## 受け入れ条件

- `paper_structure.yaml`と`chat_tool_calls.yaml`に、それぞれ最低10件程度のCaseが用意されている
- dev/prod両モデルに対して6指標すべてが算出され、JSONとして保存される
- 2回目以降の実行で、前回結果との差分(数値の増減)が確認できる

## 未決定事項

- Logfire連携を導入するか(リトライ・レイテンシの精度を上げられるが外部サービス依存が増える)
- Case集をどこまで手動キュレーションするか(最初は手作業で少数から始める想定)

## 依存

- `002-papers-ingest-full`(完了済み、構造化抽出の実データが必要)
- `001-walking-skeleton`/`003-chat-ui-polish`(tool呼び出しの実データが必要)
