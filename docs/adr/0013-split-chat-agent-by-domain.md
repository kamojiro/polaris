# 0013. chat_agent.pyをドメインごとのファイルに分割する

## ステータス

採択

## コンテキスト

`agent/chat_agent.py`が585行まで育ち、論文Ingest(002/014)・論文QA(015)・TODO読み書き(007)・Web検索(018)・ニュース一覧(008)・記憶注入(017)という6ドメイン分の`tool`定義・応答モデル・整形関数・巨大な`_INSTRUCTIONS`プロンプト文字列が1ファイルに同居している。`011-agent-registry`のspecが「着手判断の参考」として記録していた兆候(007のTODO tool追加時点で既にruffのC901/PLR0915を超え、`_register_*`関数への分割が必要になった)が、その後の013/017/008/018の追加でさらに進行した状態。

今回のリファクタリングの動機は、実装者本人(人間)が直接手を動かして感じている痛みではなく、**実装をClaude Codeに任せる運用(ADR-0007)における見通しの悪化**。1ドメインのtoolを直すだけでも、無関係な他ドメインのtool定義・instructions・応答モデルまで同じファイル内に見えてしまい、変更範囲の把握・レビューが無駄に広くなる。

## 決定

`chat_agent.py`を、ドメインごとのtool登録ファイルに分割する。

```
agent/tools/paper.py       — save_paper/list_papers (002/014)
agent/tools/paper_qa.py    — get_paper_full_text/exit_paper_mode、PaperModeState (015)
agent/tools/todo.py        — add_todo/list_todos/update_todo/complete_todo/delete_todo (007)
agent/tools/web_search.py  — web_search (018)
agent/tools/news.py        — list_news (008)
agent/tools/memory.py      — 記憶の動的instructions注入 (017)
agent/chat_agent.py        — ChatDepsの定義 + 上記を集めてbuild_chat_agent()を組み立てるだけの薄い役割
```

各ファイルは自分のドメイン分の`_INSTRUCTIONS`断片も持ち、`build_chat_agent()`が結合して1つのinstructionsを組み立てる(LLMに渡る最終的な内容・実行時のエージェント構成は変えない、ファイル分割のみ)。

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
