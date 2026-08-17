# 004. 引用関係取得(Semantic Scholar API)

## ステータス

未着手

## 概要

ライブラリ内(既にIngest済み)の論文同士の引用関係をSemantic Scholar APIから取得し、汎用`Relation`テーブルに`cites`エッジとして保存する。`002-papers-ingest-full`では意図的にオプション扱いにして外してあった部分。

## スコープ判断: スタブレコードは作らない

Semantic Scholarから返ってくる引用/被引用論文の多くは、まだ自分のライブラリに取り込んでいない論文になる。これに対して2つの方針が考えられる。

- (A) 未取り込みの論文も最小限のItem/PaperRecord(スタブ)として作成し、引用グラフを充実させる
- (B) 既にライブラリにある論文同士だけをRelationで繋ぎ、未取り込みの論文はレコードを作らない

本specは(B)を採用する。理由は、このツールが「実際に読んだ/興味を持った論文を整理する」ためのものであり、引用網羅のための未読論文でDBが埋まると検索・一覧のノイズになるため。将来「読みたい論文リスト」のようなItemの状態(want-to-read等)を導入することになったら、その時にスタブ導入を再検討する。

代わりに、未取り込みの引用/被引用は集計値として`PaperRecord`に記録し(件数のみ)、「まだ読んでいないがよく引用されている関連論文がある」という発見のシグナルとして後のSurfaceフェーズで使えるようにする。

## データモデル追加

```python
from datetime import datetime
from pydantic import BaseModel


class Relation(BaseModel):
    id: str
    from_item_id: str  # 引用する側のItem.id
    to_item_id: str     # 引用される側のItem.id
    relation_type: str  # "cites"
    created_at: datetime
```

`PaperRecord`に集計フィールドを追加する:

```python
class PaperRecord(BaseModel):
    # ...(既存フィールド)
    known_reference_count: int = 0  # ライブラリ内で見つかった参照文献数
    known_citation_count: int = 0   # ライブラリ内で見つかった被引用数
    external_reference_count: int = 0  # ライブラリ外(未取り込み)の参照文献数
    external_citation_count: int = 0   # ライブラリ外(未取り込み)の被引用数
```

## 処理フロー

1. 対象の`PaperRecord`(arxiv_id または doi を持つもの)について、Semantic Scholar APIの`/graph/v1/paper/{paper_id}/references`と`/citations`を呼ぶ(`paper_id`は`arXiv:XXXX`または`DOI:XXXX`形式でそのまま指定可能)
2. 返ってきた各論文のexternalIds(arxiv_id/doi)で、自分のライブラリ内に一致する`PaperRecord`があるか検索
3. 見つかった場合: `Relation`(`cites`)を作成し、`known_reference_count`/`known_citation_count`をインクリメント
4. 見つからなかった場合: レコードは作らず、`external_reference_count`/`external_citation_count`をインクリメントするのみ

## エラーハンドリング・レート制限

Semantic Scholar APIは未認証だとレート制限が厳しい(共有プールで実質1req/秒程度という報告がある)。論文をIngestするたびに同期的に呼ぶのではなく、明示的なコマンド("引用関係を取得して"等)またはバックグラウンドジョブとして遅延実行する運用にする。無料のAPIキー取得を推奨(取得すると上限が上がる)。レート制限やAPIエラーで失敗してもIngest全体は失敗させず、警告として記録する(002のエラーハンドリング方針を踏襲)。

## 受け入れ条件

- ライブラリに2本以上の論文があり、片方がもう片方を引用している場合、`cites`の`Relation`が1件作られる
- 未取り込みの論文への引用は`Relation`を作らず、`external_*_count`に反映される
- Semantic Scholar APIのレート制限やエラーが発生しても、Ingest処理全体は失敗しない

## 未決定事項

- arxiv_id/doiを持たない論文(手動追加等)への対応は範囲外にするか
- `known_*_count`/`external_*_count`をUI上でどう見せるか(Surfaceフェーズ、`009-dashboard`とも関係しそう)

## 依存

- `002-papers-ingest-full`(完了済み)
