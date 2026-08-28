# 0004. Hub/Satelliteパターンでデータをモデリングする

## ステータス

採択

## コンテキスト

Polarisは個人用の知識・生活管理プラットフォームとして、論文・TODO・ニュース・長期記憶・IR文書など、性質の異なる複数ドメインのデータを扱う。ドメインが増えるたびに一覧表示・チャットへの提示方法(generative UI)・横断検索を毎回作り直すのは避けたい。一方でドメインごとに固有のフィールド(論文なら著者・出版年、TODOなら締切バケット、ニュースなら情報源ラベル等)は当然異なり、単純に同じテーブルにまとめることはできない。

## 決定

汎用の`Item`テーブル(hub: `id`/`item_type`/`title`/`summary`/`created_at`/`source_ref`)と、ドメイン固有の`Satellite`テーブル(`PaperRecord`/`TodoRecord`/`NewsRecord`/`MemoryTheme`等)を1:1で対にする形でデータをモデリングする。`Item.source_ref`が対応するSatelliteレコードを指す(例: `"paper:{PaperRecord.id}"`)。

## 検討した代替案

- ドメインごとに完全に独立したテーブル群(共通の基底なし): 一覧表示・横断検索のたびにドメイン数だけ分岐コードが要る。ドメインが増えるほど組み合わせが増え続ける。
- 単一の巨大テーブルに全ドメインのカラムを集約(EAV的、あるいは全カラムをNULL許容で持つ): クエリはシンプルになるがスキーマが早期に汚染され、型安全性も失われる。

## 結果(Consequences)

良い面: 一覧・検索・チャットのgenerative UIパターン(`list_X`ツール→専用Reactコンポーネント)をドメイン間で使い回せる。新ドメイン追加時はSatelliteテーブル1つ+専用adapterを足すだけで済む(実際に002→007→008→017とこの型で増えてきた)。

悪い面: 1件の完全なレコードを引くのにItemとSatelliteの2テーブルJOINが常に必要になる。Item側の共通フィールド(`summary`等)とSatellite固有のフィールドとの責務分担を都度判断する必要がある(例: 008でNewsRecordの要約をどちらに置くか)。

## 関連

- `docs/constitution.draft.md`
- `002-papers-ingest-full`以降、ほぼ全specで使用
