# 008. 日次まとめツール(エコーチェンバー可視化)

## ステータス

⏸ 待機中(Phase Aは完了、Phase Bは`009-dashboard`待ち。詳細は下記)

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

## Ingestソース候補(2026-08-23、技術系記事中心で調査)

ユーザーが日常的に読むのは技術系記事(AI/LLM、ソフトウェア工学一般、日本のテックブログ、一般テック業界ニュース)。この4分類が、そのまま「対立軸の定義方針」で言うsource_labelの初期セットとして使えそうと分かった(政治的傾向軸ではなく、技術領域の偏りに気づくための軸)。

- **`ai_llm`**: 以下いずれも候補
  - arXiv公式のカテゴリ別RSS。ユーザーの関心(ソフトウェア工学・機械学習・AIエージェント・情報検索/埋め込み、2026-08-23確認)に合わせて`https://rss.arxiv.org/rss/cs.LG+cs.AI+cs.MA+cs.IR`(機械学習+総合AI+マルチエージェントシステム+情報検索)を候補にする。完全に公式・安定で、論文そのものの新着を追える。ダイジェストで気になったものは既存の`save_paper`/URL Ingest(002/014)でそのまま論文ライブラリに取り込む運用を想定(IDEAS.mdの`search_arxiv`(能動的キーワード検索)とは補完関係)。自然言語処理全般(`cs.CL`)は言語学寄りの論文も混ざり範囲が広すぎるため、v1では外す(必要になれば追加できる)
  - 「ローカルLLM推論・高速化」「エージェント評価・ベンチマーク」への関心は、専用のarXivカテゴリが無く`cs.LG`/`cs.AI`に既に混在しているため、新規カテゴリの追加は不要(上記の組み合わせでカバー済み)。推論高速化系をさらに厚く拾いたい場合`cs.DC`(分散・並列計算)も候補になるが、LLMと無関係な分散システム全般の論文も大量に混ざり範囲が広すぎるため、v1では見送り、必要になったら追加を検討する
  - Simon Willisonのブログ(`https://simonwillison.net/atom/everything/`、公式・安定)
  - ニュースレター: Ahead of AI(Sebastian Raschka、論文解説が強い)、Latent Space(swyx、AIエンジニアリング寄り)。いずれもSubstack系で`/feed`形式のRSSがある想定(着手時に確認)。Import AI(Jack Clark)は2026年3月頃からAIリスク・政策寄りに軸足を移しており、論文カバレッジの比重は下がっている点に留意
  - Hugging Face Papers(毎日の注目論文キュレーション)は公式RSSが存在せず、非公式ミラー(例: `huangboming/huggingface-daily-paper-feed`)頼みになる点に注意(下記リスク参照)
  - Anthropic公式ブログも公式RSSが存在せず、非公式ミラー(例: `conoro/anthropic-engineering-rss-feed`)頼みになる(同上)
- **`swe_general`**: arXiv cs.SEカテゴリ(`https://rss.arxiv.org/rss/cs.SE`、ユーザーの関心領域として確認済み)に加えて、以下の個別ブログ・メディアを候補にする(2026-08-26、いずれも実機で200応答・パース可能・直近記事ありを確認済み)
  - Martin Fowlerのブログ(`https://martinfowler.com/feed.atom`、公式・安定、設計・アーキテクチャ論)
  - InfoQ(`https://www.infoq.com/feed/`、公式、ソフトウェア工学全般のニュース・カンファレンス講演)
  - The Pragmatic Engineer(`https://newsletter.pragmaticengineer.com/feed`、Gergely Oroszのニュースレター、Substack系、エンジニアリング組織論寄り)
  - Julia Evansのブログ(`https://jvns.ca/atom.xml`、公式・安定、実務寄りの深掘り記事)
  - the morning paper(`https://blog.acolyer.org/feed/`、Adrian Colyerによる論文解説ブログ。`ai_llm`ではなくCS全般の論文を扱うため`swe_general`側に分類)
- **`jp_tech_blog`**: Zennトレンド(`https://zenn.dev/feed`)、Qiitaトレンド(`https://qiita.com/popular-items/feed`)、はてなブックマーク テクノロジー人気エントリー(`http://b.hatena.ne.jp/hotentry/it.rss`)。いずれも公式・安定
- **`tech_industry_news`**: Hacker News。公式(`https://news.ycombinator.com/rss`)より`https://hnrss.org/frontpage`の方がポイント数・コメント数等のメタデータやキーワードフィルタが使え、こちらを優先候補にする

**運用上のリスク**: Anthropicの例のように、公式RSSを持たない情報源は非公式ミラー(サードパーティのRSS生成サービス)に頼ることになり、ミラーが停止するとIngestが静かに壊れる。v1は公式RSSが存在する情報源を優先し、非公式ミラー頼みの情報源は後回しにする。

はてなブックマーク/Qiitaトレンドのようなアグリゲータ系フィードは複数の書き手・媒体が混在するため、source_labelは個々の記事ではなく「そのフィード自体」に対して付与する(静的ソースラベル方式の前提通り)。

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

## タクソノミーの扱い(2026-08-26決定)

上記4分類(`ai_llm`/`swe_general`/`jp_tech_blog`/`tech_industry_news`)はv1では固定する。017のテーマ再編のような明示指示での見直し機能は入れない。理由: 017のテーマ再編自体まだ実戦投入されておらず使用感が未知数なため、008では固定で始めて様子を見る。分類を増やしたくなったら別specとして拡張する。

## 巡回頻度・スケジューリング方式(2026-08-26決定)

基本は1日1回。`wishlist-design.md`はこのセッションの時点でリポジトリ中に見当たらない(006/008/009/010/011/012/016が参照していた元ドキュメントだが所在不明、`specs/README.md`の実装順検討時から既知の状態)ため、その「バッチ処理方針」は参照できず、ここで方式を新規に決める。

個人用ツールの規模でスケジューラ常駐(APScheduler等をuvicornプロセスに組み込む)を導入するのはYAGNIと判断し、**OSのcronから独立したCLIスクリプトを1日1回叩く**方式にする(`uv run python -m polaris.cli.ingest_news`のようなエントリポイントを想定)。理由:

- FastAPIサーバーが起動していない時間帯でも確実に巡回できる(サーバー常駐に依存しない)
- 既存のIngestパイプライン(`services/ingest_paper.py`と同じ形)をCLIから直接呼ぶだけで済み、Web層を経由する必要がない
- `uv run uvicorn ... --reload`を開発中に何度も再起動する運用と、スケジュールされたバッチ処理は生存期間の性質が違うため、同じプロセスに同居させない方が事故りにくい

## Phase A 実装状況(2026-08-26)

- 依存: `feedparser`を新規追加(RSS 2.0/Atomの差異吸収を自前実装せず既存ライブラリに任せる)
- データモデル: `domain/entities.py`に`ItemType.news_article`/`NewsRecord`を追加(`Relation`/`Event`はPhase B、未実装)
- adapter: `adapters/rss/client.py::fetch_feed()`。HTTP取得はhttpx、パースはfeedparserを`asyncio.to_thread`で呼ぶ。`published_parsed`が無いAtomフィード(実機確認: Martin Fowlerのブログ)は`updated_parsed`にフォールバックする。`follow_redirects=True`が必須(実機確認: InfoQ/はてなブックマークは301リダイレクトを返し、これが無いと`httpx`の`raise_for_status()`自体がエラー扱いにする。`adapters/pdf/downloader.py`と同じ対応)
- Structure: `agent/structure_news.py`(`structure_paper.py`と同型、reasoning無効化)。記事単位のトピック分類はしない(source_labelはフィード単位で静的に決まるため)
- Ingest: `services/ingest_news.py::ingest_all_feeds()`。`source_url`で重複防止(冪等)、1フィードのHTTP失敗が他フィードを止めない
- CLI: `cli/ingest_news.py`(`uv run python -m polaris.cli.ingest_news`)。OS cronから叩く想定、FastAPIサーバーの生存に依存しない
- チャット: `list_news`ツール(`agent/chat_agent.py`)、`NewsList.tsx`(source_labelごとにバケット分けするgenerative UI、`TodoList.tsx`と同型)
- E2E検証(実機・実LLM): `uv run python -m polaris.cli.ingest_news`を実際に実行し、既定の12フィードから記事を取得・要約生成・DB保存できることを確認。同じコマンドを再実行すると`skipped`が増え重複保存されないこと(冪等性)も確認

### arXivフィードの流量対応(2026-08-27)

実機検証で、arXivの2フィード(cs.LG+cs.AI+cs.MA+cs.IR/cs.SE)だけ1日あたりの実際の流量が既定の`max_entries_per_feed=20`を大幅に超える(前者565件/日、後者62件/日、いずれも実機調査時点)ことが判明した一方、他の10フィードは20件以内にほぼ収まっていた。以下の方針で対応した:

- 「興味があるかどうかはabstractで十分、arXiv自体は1行(タイトル)で十分」という判断により、`NewsFeed.skip_summary`(既定`False`)を追加し、arXivの2フィードのみ`True`にした。`skip_summary=True`のフィードは`structure_news`のLLM要約呼び出し自体をスキップし、`Item.summary`を空文字のまま保存する(`services/ingest_news.py`)。LLM呼び出しコストが無くなったため、`NewsFeed.max_entries`(フィード単位の上限、既定は`None`で`NewsSettings.max_entries_per_feed`にフォールバック)をarXivの2フィードだけ100/70に引き上げた
- `NewsList.tsx`は`summary`が空文字の場合、要約行(`.news-summary`)自体を描画しない(タイトル+情報源名のみの1行表示になる)
- `NewsRepository.list_news()`は`limit`(全体への単一SQL LIMIT)から`limit_per_label`(source_labelごとの上限)に変更した。理由: 全体に単一LIMITをかけると、更新頻度の高いソース(Hacker News等)が更新頻度の低いソース(arXiv、投稿日単位のタイムスタンプ)を一覧から完全に押し出してしまうことが実機で確認できた(arXivの取り込み件数を増やした直後、`list_news`の結果に一件もarXiv記事が含まれなくなった)。`chat_agent.py`の`_RECENT_NEWS_LIMIT_PER_LABEL`(既定15)で呼び出す
- 「他の記事(ブログ等)から実際に参照されているarXiv論文だけ、通常より踏み込んで全文を読んで説明を加える」という発展的な着想は本Phase Aの範囲外とし、`specs/IDEAS.md`に記録した(相互参照ロジックが必要で、単純な「1フィードずつ処理」というPhase Aの構造とは別設計が要るため)

## 未決定事項

- `Relation`のエッジ判定基準(embedding類似度の閾値、上位N件のみ繋ぐか等)
- `009-dashboard`が無い間、Phase Bをどう暫定的に見せるか(専用の簡易ページを先に作るか、009自体を前倒しするか)

## 依存

- Phase A: 特になし(既存のChunk/Embedding基盤・生成UIパターンを再利用)
- Phase B: `009-dashboard`(グラフ表示に必要)
