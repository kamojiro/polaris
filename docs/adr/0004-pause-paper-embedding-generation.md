# 0004. 論文Ingest時のEmbedding生成を一時停止する

## ステータス

採択

## コンテキスト

`002-papers-ingest-full`では、arXiv論文のIngest時に`Qwen/Qwen3-Embedding-0.6B`でChunk embeddingを生成し、sqlite-vecのvec0テーブルに保存する設計にした。当初の想定(`wishlist-design.md` Layer1)は「ハイブリッド検索(FTS5+ベクトル)によるライブラリ横断検索」だった。

しかし実装が進むにつれて状況が変わった。

- `015-paper-qa-chat`(1論文とのチャット)は、埋め込み検索特有の精度問題(正しいチャンクを引き当てられるか)を避けるため、対象論文の全文をそのままコンテキストに渡す方式を採用し、embeddingを一切使わない設計にした
- `013-ir-analysis-domain`もv1では同じ理由でChunk/Embeddingを作らない判断をした(「ライブラリ横断検索の需要が今のところ無い」)
- `008-daily-digest-domain`のPhase B(Relate)は将来embeddingを使う想定だが、`009-dashboard`待ちでまだ実装されていない

実コード(`src/polaris/db/repository.py`、`src/polaris/services/ingest_paper.py`)を確認したところ、`save_embeddings()`で保存したベクトルを読み出して類似検索する経路(KNNクエリ等)はどこにも実装されておらず、`list_chunks()`は全文再構成のフォールバック用途でのみ使われていることが分かった。つまり、Ingestのたびに生成しているembeddingを消費する機能が、この時点で1つも存在しない。この計算は既に一度CUDA OOMの原因になっており(`Load the embedding model in fp16 to fix a real-world CUDA OOM`)、実際のコストも発生している。

## 決定

論文Ingest時のChunk embedding生成(`services/ingest_paper.py`のembedding生成ステップ、およびGPU上でのembeddingモデルロード)を一時停止する。`Chunk`テーブル自体(セクション分割されたテキスト、全文再構成フォールバックやFTS5用途で使う)は残す。`save_embeddings()`・`vector_store.py`のコード自体も削除せず残す(再開時の手戻りを減らすため)。

## 検討した代替案

- 現状維持(生成し続ける): 「そのうち使うかもしれない」という理由だけでGPUコスト・OOMリスク・コードの複雑度を払い続けることになり、このプロジェクトが他の箇所(004/005/XBRL構造化解析/Interestベクトル等)で一貫して採用してきた「使う機能が具体化してから作る」というYAGNI方針と矛盾する
- embedding基盤ごと削除する(`vector_store.py`・sqlite-vec依存を完全撤去): `008`のPhase Bで将来使う可能性が具体的に見えているため、テーブル定義・保存コードは残し、呼び出しだけ止める方が再開時の手戻りが小さい

## 結果(Consequences)

良い面: Ingestのレイテンシとピーク時のGPUメモリ消費が下がり、OOMリスクが減る。使われていない機能のためのコード経路が動かなくなり、認知負荷が下がる。

悪い面: 将来`008`のPhase Bやライブラリ横断検索が本当に必要になったとき、既存の保存済み論文に対してembeddingの再計算(再Ingest相当の処理)が必要になる。Ingest自体は冪等に作られているため、技術的な再実行の難度は高くない想定だが、実データでの検証はまだしていない。

## 関連

- 関連spec: `specs/002-papers-ingest-full`(Embedding生成ステップの一時停止)、`specs/015-paper-qa-chat`(embedding不要という判断の先例)、`specs/013-ir-analysis-domain`(同様の判断の先例)、`specs/008-daily-digest-domain`(Phase Bでの将来的な再開候補)
