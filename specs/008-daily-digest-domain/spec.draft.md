# 008. 日次まとめツール(エコーチェンバー可視化)

## ステータス

⏸ 待機中(Phase Aは着手可能、Phase Bは`009-dashboard`待ち。詳細は下記)

## 概要

外部のニュース・RSSを取り込み、関係グラフとして可視化する。詳細閲覧から興味プロファイルを更新し、「自分の情報摂取が偏っていないか」に気づけるようにする。Xは有料APIのためv1の情報源から外し、RSS/ニュースAPIのみを対象にする。

「エコーチェンバー可視化」の核心である**対立軸(情報源の傾向・スタンス)の定義**は、LLMによる自動スタンス推定ではなく、**ユーザーが情報源単位で手動ラベリングする**方式を採る(詳細は下記「対立軸の定義方針」)。

## 背景・判断(2026-08-23)

- `wishlist-design.md` 3-2節の「留意点」で「対立軸の定義自体が難しく、技術より設計判断が先に来るテーマ」と明記されていた。この設計判断を先に固める
- 現在の実コード(`domain/entities.py`)には`Relation`/`Interest`/`Event`(Layer1で構想されていたテーブル)がまだ1つも実装されていない。008が最初にこれらを必要とするドメインになる
- v1では`Interest`(閲覧行動からのベイズ的/指数減衰更新)は作らない。まず`Relation`(記事間の関係)と`Event`(閲覧ログ)だけを実装し、Interestベクトルの計算はデータが溜まってから改めて設計する(002が引用関係の作り込みを見送ったのと同じ考え方)
- 「関係グラフの詳細ドリルダウン表示」はチャットの生成UI(PaperList.tsx的なリスト表示)には収まらない。グラフ描画(D3.js/Cytoscape.js想定)には専用のページが要るため、`009-dashboard`への依存が生まれる。ただしIngest/Structure(記事取り込み・要約・チャットでの一覧)まではチャット単体で完結できるため、フェーズを分けて後者だけ先に着手可能にする

## 対立軸の定義方針: 静的ソースラベル方式

記事単位でLLMに「この記事のスタンスは何か」を自動推定させる方式は採らない。理由は2つ。

1. 政治的スタンス等の自動分類は本質的に主観的・論争的で、LLMの判定が体系的に偏っていた場合、ユーザーに誤った「自分の情報摂取の偏り」認識を与えかねない
2. 技術的にも記事単位のスタンス推定は不安定になりやすい

代わりに、**情報源(RSSフィード)単位でユーザー自身がラベルを付ける**(例: 「経済メディアA」に`business`、「独立系ブログB」に`independent`)。ラベルの軸自体も政治的傾向に限定せず、情報源の性質(主流/独立系、一次情報/論評 等)を軸にすることもできる。この方針なら:

- Polaris側は「決められたラベルに基づいて記事をグルーピングして見せる」だけの実装で済み、主観的な自動判定ロジックを持たずに済む
- ラベルの定義・粒度はユーザーが完全にコントロールできる(タクソノミー自体は未決定事項、下記参照)

## フェーズ分割

### Phase A: Ingest/Structure(独立して着手可能)

- Ingest: RSS/ニュースAPIから記事を取得
- Structure: 要約生成、トピック分類(既存の`structure_paper.py`/`extract_metadata.py`と同じ「狭いタスクの軽量LLM呼び出し」パターンを踏襲)
- チャットの生成UI(既存の`PaperList.tsx`/`TodoList.tsx`と同じパターン)で一覧表示するところまでを含む
- `018-web-search-tool`のSearXNG連携とは役割が異なる(こちらは能動的な検索、008は受動的な定期取り込み)ため、依存関係はない

### Phase B: Relate/Surface(`009-dashboard`待ち)

- Relate: 記事間のトピック類似度(既存のChunk/Embedding基盤を再利用)による`Relation`エッジ、および情報源ラベルによるグルーピング
- Surface: 関係グラフの表示(D3.js/Cytoscape.js等)、ドリルダウン
- Feedback: `Event`(閲覧ログ)の記録まではPhase Bでやる。`Interest`ベクトルの更新はさらに後回し(前述)

## データモデル(たたき台)

```python
class ItemType(StrEnum):
    ...
    news_article = "news_article"


class NewsRecord(SQLModel, table=True):
    __tablename__ = "news_records"

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    source_name: str          # RSSフィード名等
    source_label: str          # ユーザー定義のラベル(対立軸の定義方針を参照)
    published_at: datetime
    source_url: str


class Relation(SQLModel, table=True):
    __tablename__ = "relations"

    id: str = Field(primary_key=True)
    from_item_id: str = Field(foreign_key="items.id", index=True)
    to_item_id: str = Field(foreign_key="items.id", index=True)
    relation_type: str   # "topic_similar" 等
    weight: float | None = None


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    event_type: str   # "viewed" 等
    occurred_at: datetime
```

`Relation`/`Event`は008で初めて実体を持つが、汎用テーブル(`Item`と同階層)として設計する。将来他ドメイン(論文の引用関係等)からも再利用できる想定。

## 未決定事項

- 具体的なRSS/ニュースAPIの選定(候補調査は着手時)
- ソースラベルの具体的なタクソノミー(いくつのラベルを持つか、政治的傾向軸にするか情報源タイプ軸にするか等はユーザー自身が決める運用にするか、初期セットをPolaris側で提案するか)
- `Relation`のエッジ判定基準(embedding類似度の閾値、上位N件のみ繋ぐか等)
- `009-dashboard`が無い間、Phase Bをどう暫定的に見せるか(専用の簡易ページを先に作るか、009自体を前倒しするか)
- RSSの巡回頻度・スケジューリング方式(cron想定、`wishlist-design.md`のバッチ処理方針を踏襲)

## 依存

- Phase A: 特になし(既存のChunk/Embedding基盤・生成UIパターンを再利用)
- Phase B: `009-dashboard`(グラフ表示に必要)
