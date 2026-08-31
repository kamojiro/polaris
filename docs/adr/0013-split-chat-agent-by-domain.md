# 0013. chat_agent.pyをドメインごとのファイルに分割する

## ステータス

採択・実装済み(2026-08-31)

## コンテキスト

`agent/chat_agent.py`が585行まで育ち、論文Ingest(002/014)・論文QA(015)・TODO読み書き(007)・Web検索(018)・ニュース一覧(008)・記憶注入(017)という6ドメイン分の`tool`定義・応答モデル・整形関数・巨大な`_INSTRUCTIONS`プロンプト文字列が1ファイルに同居している。`011-agent-registry`のspecが「着手判断の参考」として記録していた兆候(007のTODO tool追加時点で既にruffのC901/PLR0915を超え、`_register_*`関数への分割が必要になった)が、その後の013/017/008/018の追加でさらに進行した状態。

今回のリファクタリングの動機は、実装者本人(人間)が直接手を動かして感じている痛みではなく、**実装をClaude Codeに任せる運用(ADR-0007)における見通しの悪化**。1ドメインのtoolを直すだけでも、無関係な他ドメインのtool定義・instructions・応答モデルまで同じファイル内に見えてしまい、変更範囲の把握・レビューが無駄に広くなる。

## 決定

`chat_agent.py`を、ドメインごとのtool登録ファイルに分割する。

```
agent/chat_state.py        — ChatDeps/ChatUIState/ActivePaper(下記「実装時の訂正」参照)
agent/tools/paper.py       — save_paper/list_papers (002/014)
agent/tools/paper_qa.py    — get_paper_full_text/exit_paper_mode、ActivePaper (015)
agent/tools/todo.py        — add_todo/list_todos/update_todo/complete_todo/delete_todo (007)
agent/tools/web_search.py  — web_search (018)
agent/tools/news.py        — list_news (008)
agent/tools/memory.py      — 記憶の動的instructions注入 (017)
agent/tools/ir.py          — save_ir_document/get_ir_full_text/list_ir_documents (013)
agent/tools/diary.py       — get_diary_range/set_diary_mode (019)
agent/chat_agent.py        — 上記を集めてbuild_chat_agent()を組み立てるだけの薄い役割(ChatDeps/ChatUIStateはchat_state.pyから再エクスポート)
```

各ファイルは自分のドメイン分の`_INSTRUCTIONS`断片(モジュール定数`INSTRUCTIONS`)も持ち、`build_chat_agent()`が結合して1つのinstructionsを組み立てる(LLMに渡る最終的な内容・実行時のエージェント構成は変えない、ファイル分割のみ)。

### 実装時の訂正(2026-08-31実装)

当初案は「013(IR)・019(diary)は対象外、`ChatDeps`は`chat_agent.py`が定義」だったが、実装時に2点訂正した。

1. **対象ドメインに013・019を追加**: ADR起票後に013(IR)・019(diary)が実装され、`chat_agent.py`はコンテキストに書いた585行から860行まで育っていた。分割の動機(見通しの改善)はこの2ドメインにも当然当てはまるため、`agent/tools/ir.py`・`agent/tools/diary.py`も追加した。
2. **`ChatDeps`/`ChatUIState`/`ActivePaper`は`chat_agent.py`ではなく専用の`agent/chat_state.py`に定義**: 当初案通り`chat_agent.py`に置くと循環importになる。`agent/tools/paper_qa.py`(`get_paper_full_text`)・`agent/tools/diary.py`(`set_diary_mode`)・`agent/tools/memory.py`(`_memory_instructions`)は`RunContext[ChatDeps]`を引数に取る`@agent.tool`/`@agent.instructions`関数を持ち、pydantic-aiが登録時に`get_type_hints`でシグネチャを実行時解決するため`ChatDeps`の実importが必要(`from __future__ import annotations`下でもTYPE_CHECKINGブロックに退避すると`NameError`になる、019の`diary_date_infer.py`で踏んだのと同種のバグ)。`chat_agent.py`がChatDepsを定義しつつ各`agent/tools/*.py`のtool登録関数もimportする構成だと、`agent/tools/*.py`側が`ChatDeps`を`chat_agent.py`から逆import する形になり循環する。そのため`ChatDeps`/`ChatUIState`/`ActivePaper`だけを依存の無い`chat_state.py`に切り出し、`chat_agent.py`・`agent/tools/*.py`の両方がそこから一方向にimportする形にした。外部からの参照(`api/app.py`の`from polaris.agent.chat_agent import ChatDeps, ChatUIState, build_chat_agent`)は`chat_agent.py`が再エクスポートすることで変更不要にした。

分割前後でLLMに渡る最終的な`_INSTRUCTIONS`文字列がバイト単位で完全に一致することをハッシュ比較で確認済み(振る舞いのリグレッションが無いことの機械的な裏付け)。

## 検討した代替案

- `011-agent-registry`(固定チーム型マルチエージェント)を今着手する: 「1つの巨大instructionsだとLLMのtool選択精度が落ちる」というような**具体的な兆候**が出てから着手する話であり、今回の動機(ファイルが長く見通しが悪い)だけでは、ルーティング・エージェント間state共有といった実行時の複雑さを持ち込む理由が無い。011は`specs/011-agent-registry`に「着手トリガー待ち」のまま残す
- ドメインエンティティ(`domain/entities.py`)をSQLModel(ORM行)から独立した純粋ドメイン型に切り離す: クリーンアーキテクチャの依存関係のルールには近づくが、変換関数・ファイル数が増える分、AIが追うべき箇所はむしろ増える。今回の目的(見通しの改善)には逆効果と判断し見送り
- 現状維持: 013(IR)・019(diary)・026(voice-input)など今後もドメインが増える見込みで、先送りするほど1ファイルの複雑度が上がり分割コストも上がる

## 結果(Consequences)

良い面: 1ドメインの変更が1ファイルに閉じる。Claude Codeに実装を頼む際、渡すべきファイルの範囲が明確になる。実行時のエージェント構成・LLMへの最終的な入力は変わらないため、振る舞いのリグレッションリスクが低い。

悪い面: ファイル数が増え、`build_chat_agent()`側の配線(import・登録呼び出し)がやや増える。instructions断片を各ファイルに分散させる分、「全体としてLLMに何を指示しているか」を一望するには`build_chat_agent()`を経由して組み立てを追う必要がある。

## 関連

- 関連spec: `specs/011-agent-registry`(この分割は011の前段、011自体はまだ着手しない)、`specs/007-todo-domain`(複雑度超過の最初のシグナル)
- 関連ADR: ADR-0003(パイプライン構造、今回の分割で変えない)
