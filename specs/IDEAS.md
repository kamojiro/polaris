# アイデア置き場

まだspecにするほど固まっていない、作業中に思いついたことのメモ。specの体裁(概要・受け入れ条件など)を整える手前の雑多な置き場なので、書式は問わない。着手する気になったら該当specへ書き足す(無ければ新規spec化する)か、`specs/README.md`の一覧に載せる。

## 既知の不具合(未対応)

- **toolのstreaming時ハング**: `AGUIAdapter`のstreaming経路(`agent.run_stream_events()`)で、tool呼び出しの引数をモデルがストリーミングし終えた(はずの)直後に後続イベントが来ずSSEが無限にハングすることがある(非streamingの`agent.run()`では発生しない)。`018-web-search-tool`のE2E検証中に`list_papers`(引数無し)で発見し、origin/main(018の変更を含まない状態)でも4回中3回再現したため018固有の問題ではないと確認していたが、2026-08-25に実運用中`save_paper(url=...)`(引数**あり**)でも同じ症状(openrouterからの応答は届いているのに`tool call: save_paper(...)`のログが出ないまま数分単位で無反応)を確認した。**引数の有無に限定された問題ではなく**、tool呼び出しの完了検知全般に関わる可能性が高い。おそらく`qwen/qwen3-30b-a3b:free`のツール呼び出しストリーミングのゆらぎにpydantic-ai側の完了検知が追随できていない。原因調査(pydantic-ai側のツール呼び出し完了判定ロジック)が必要。回避策は今のところ「フロントをリロードして再送する」のみ(toolの多くは冪等なので再送は安全)。影響範囲が広い(既存のtool全般が対象になりうる)ため優先度を上げて専用に調査する(2026-08-24発見、2026-08-25再発、2026-08-27に`list_news`(引数無し)のE2E確認中4回中4回再現・ログでは`tool call: list_news()`が出た直後に後続ログが一切無く止まっていることを確認、再現率がさらに悪化している可能性)
- **Ingestの冪等性チェックがembeddingの有無を見ていない**: `services/ingest_paper.py`の「既にIngest済みなのでスキップ」判定は`repo.list_chunks(item.id)`が非空かどうかだけで判断しており、embedding(sqlite-vecの`embeddings`テーブル)が実際に生成済みかは見ていない。上記のGPU OOM(fp16化で対応済み、`adapters/embeddings/qwen.py`参照)でchunk分割まで終わった直後にEmbedding生成が失敗した場合、chunkだけがDBに残り、以後同じURLを再送しても「既に取り込み済み」として無条件にスキップされ続け、embeddingが永久に欠けたまま(要約も、その失敗した回に生成された古い内容のまま)になる。今回は手動でItem/PaperRecord/Chunkを削除して再送することで復旧した。判定条件をchunk数ではなくembedding数(またはchunk数とembedding数の一致)に変えるのが本来の直し方(2026-08-25)

## 未整理

- **自己更新可能な設定値**: `usd_jpy_rate`のような「たまに手動更新すればいい値」を`.env`/settings.pyの静的値ではなくDB/JSONなどdata領域に持たせ、チャットで「(為替を)再取得して」のように話しかけるとエージェントがWeb検索して値を更新してくれる仕組み。今は`usd_jpy_rate`1つだけの話だが、同じパターンが欲しい設定値が増えてきたら専用スペック化を検討する(`015-paper-qa-chat`の実装中の雑談から、2026-08-22)
- **ニュース一覧からarXiv論文モードへの直接エントリー**: `008-daily-digest-domain`の`NewsList.tsx`で、記事がarXiv論文(`source_url`が`arxiv.org`)の場合、タイトル横に論文アイコン等の記号を出し、クリックすると`save_paper`→論文モード(015)へ直接入れるようにする着想。`PaperList.tsx`の「タイトルクリックで論文モードへ」(015追加提案、実装済み)と同じ`sendMessage()`パターンが使えそうだが、ニュース由来の記事はまだ`save_paper`で保存されていない(NewsRecordのみ)点が違うので、「保存」と「モード開始」を1クリックで両方やらせる文面(例: `sendMessage(url)`をそのまま送ってsave_paper→論文モード遷移の自然な流れに乗せる)を検討する必要がある(008 Phase A実装後の雑談から、2026-08-26)
- **他記事から参照されているarXiv論文だけちゃんと読んで説明を加える**: arXivフィード(cs.LG+cs.AI+cs.MA+cs.IR/cs.SE)は1日あたり数百件流れてくるため、Phase Aでは`skip_summary=True`にしてLLM要約自体を行わずタイトルのみのカタログ表示にした(`settings.py`のNewsFeed.skip_summary docstring、`services/ingest_news.py`参照、2026-08-27実装)。一方で、Simon Willisonのブログ記事やはてブ上位記事など**他の(arXiv以外の)ソースが特定のarXiv論文を実際に参照・言及している**場合は、その論文だけ「人間による選別」という強いシグナルが既にあるので、通常のLLM要約より踏み込んで本文まで読んだ上で説明を加える価値がある、というアイデア。実装するなら: (a) 非arXiv記事の本文/summary中からarxiv.org宛のリンクを抽出する、(b) それが指す論文が同日のarXiv Ingest分(NewsRecord)またはarXiv IDとして存在するか照合する、(c) 該当すれば`002-paper-domain`の`fetch_pdf`/PDF全文取得の仕組みを再利用して(既存の論文モードの機構と同じ)、通常のタイトルのみ表示ではなく全文ベースの要約を生成する。arXiv側とそれを参照する側のIngestタイミングがフィードによって前後する(参照記事の方が先に処理される可能性がある)ため、相互参照は全フィード取り込み後の後処理ステップとして行う必要がありそうで、Phase Aの単純な「1フィードずつ処理」構造とは別の設計が要る。「興味判定はabstractで十分、arXiv自体は1行でいい。他所で紹介されている論文だけちゃんと読む」という着想(2026-08-27の雑談)。

## 次に実装してよさそうなtool候補(2026-08-23)

「順次tool実装をやっていきたい」という雑談から出た候補一覧。優先度・spec化は未定。

- ~~**汎用Web検索tool**~~ → `018-web-search-tool`としてspec化済み(SearXNG連携)
- **`search_arxiv(query)`**: キーワード/著者でarXivを検索する(現状はID/URL直接入力のみ、`002`の範囲外)。論文ドメインの発見的検索
- **Semantic Scholar/OpenAlex API連携**: 被引用数・関連論文の取得。`004-citation-relations`(やらない判定済み)ほど作り込まず、読み取り専用の軽いtool(「この論文を引用してるのは?」程度)なら別物として検討の余地あり
- **EDINET書類一覧API(`list_recent_disclosures`)**: `013-ir-analysis-domain`のv1はdocID直接貼り付けのみ(企業名検索はAPI側に無いためv1スコープ外と明記済み)だが、日付+`filerName`のクライアント側フィルタくらいは軽いtoolとして提供できるかもしれない
- **株価/銘柄情報API**: 企業名⇔証券コード解決、簡単な株価参照。IRドメインの補助
- **XBRL部分参照tool**: `013`が範囲外とした「XBRLの構造化解析」全体はやらないが、「売上高だけ数値で欲しい」のようなピンポイント参照だけなら軽量toolとして切り出せるかもしれない
- **カレンダー連携**: TODOの締切をGoogleカレンダー等と同期。`007`のリマインド機能(将来spec)と絡む

## Google Calendar/Workspace・NotebookLM・SearXNG連携の調査(2026-08-23)

「汎用的なチャット利用のためのtool/MCP調査」の結果メモ。

- **Google Calendar/Gmail**: Googleが**公式のリモートMCPサーバー**を提供している(`calendarmcp.googleapis.com`/`gmailmcp.googleapis.com`)。自分のGoogle Cloudプロジェクトで有効化してOAuth接続する方式で、サードパーティのリレーを経由しない。Calendar MCPはlist/get/create/update/delete + 空き時間確認、Gmail MCPは検索・スレッド取得・ラベル一覧・下書き作成・ラベル付けまで(送信そのものは含まれない、安全側の設計に見える)。個人開発ならまずこちらを優先candidate。より広く(Docs/Sheets/Drive等12サービス)触りたくなったら`taylorwilsdon/google_workspace_mcp`(MIT、OAuth 2.1、自前ホスト、SaaS依存なし)が最も網羅的
- **NotebookLM**: 個人向けの公開APIは現状無い。2025年9月にEnterprise向けAPIが出たが、Gemini Enterprise/Education Premiumのアドオンライセンスが要る有償構成で、個人用途には見合わない。非公式のリバースエンジニアリング実装(`nblm-rs`)もあるがToSリスクがあるため採用は見送り。将来コンシューマー向けAPIが出たら再検討
- ~~**SearXNG**~~ → `018-web-search-tool`で自前adapter方式に決定(2026-08-23訂正。当初MCPラッパー想定だったが、APIが`GET /search?format=json`1本と単純なため、サードパーティMCPサブプロセスを挟むより自前adapterの方がシンプルと判断)
- **pydantic-aiとの繋ぎ方**: サブプロセス起動のMCPサーバーは`MCPServerStdio`、常駐サービスとして立てる場合は`MCPServerStreamableHTTP`(SSEより現行の推奨トランスポート)。あとpydantic-aiはMCPの**sampling**(MCPサーバー側がPolarisのモデル設定を借りてLLM呼び出しできる、サーバー側に個別APIキーが不要になる)と**elicitation**(tool実行中に人間へ構造化入力を求める、「送信前に確認」のような用途)にも対応している。ただしelicitationの下位プロトコルは2026-07-28のMCP仕様改定で仕組みが変わった(旧back-channel方式が廃止され、request/resubmit方式に)ばかりなので、使う際はpydantic-ai側の対応状況を都度確認する
- **参考**: Cowork(Claude)自身が今使っているCalendar/Gmail/Drive MCPのtool粒度(list/search/get + create/update/delete + ドメイン固有動詞)は、Polaris側で新しいtool群を設計する際の参考になる

### MCP vs 自前adapter、どちらで実装するか(2026-08-23改訂)

当初「汎用インフラ系はMCP、独自データモデルに紐づくものは自前adapter」という軸で考えていたが、SearXNGの検討(`018-web-search-tool`)で見直した。「汎用か独自データモデルに紐づくか」ではなく、**APIそのものの複雑さ**と**信頼できる実装の有無**で判断する方が正確。

- **MCPが向く条件**: (a) OAuth・複数エンドポイント・複雑なデータ構造など、自前実装が本当に面倒なAPIである、(b) 信頼できる(理想は公式の)実装がある。Google Calendar/Gmail/Driveがこれに該当
- **自前adapterが向く条件**: (a) 単一エンドポイント・認証なし/簡単なAPIキー程度のシンプルなAPIである。SearXNGの検索エンドポイント(`GET /search?format=json`1本)がこれに該当。サードパーティMCPサブプロセス(単一メンテナのお守りリスク、パッケージ管理コスト)を挟むより、`httpx`呼び出し1つを自前で書く方が依存を増やさずシンプル

EDINET/arXivのようにPolaris独自のデータモデル(Hub/Satellite、冪等性チェック等)に深く結びつく取り込みロジックは、上記のどちらであっても結局自前adapter(`adapters/edinet/client.py`等)に落ち着く(MCPで生データだけ取ってきても、その先の永続化ロジックは自前で書く必要があるため)。tool追加時にどちらのパターンかを都度判断する。
