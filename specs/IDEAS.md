# アイデア置き場

まだspecにするほど固まっていない、作業中に思いついたことのメモ。specの体裁(概要・受け入れ条件など)を整える手前の雑多な置き場なので、書式は問わない。着手する気になったら該当specへ書き足す(無ければ新規spec化する)か、`specs/README.md`の一覧に載せる。

## 未整理

- **自己更新可能な設定値**: `usd_jpy_rate`のような「たまに手動更新すればいい値」を`.env`/settings.pyの静的値ではなくDB/JSONなどdata領域に持たせ、チャットで「(為替を)再取得して」のように話しかけるとエージェントがWeb検索して値を更新してくれる仕組み。今は`usd_jpy_rate`1つだけの話だが、同じパターンが欲しい設定値が増えてきたら専用spec化を検討する(`015-paper-qa-chat`の実装中の雑談から、2026-08-22)

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
- **SearXNG**: 自前ホスト済みなので、既存のMCPラッパーを繋ぐだけでよい。`SecretiveShell/MCP-searxng`が基本形、並列マルチクエリ検索が欲しければ`jae-jae/searxng-mul-mcp`も候補(017の想起や007の現況調査で複数クエリを同時に投げたい場合に相性が良い)
- **pydantic-aiとの繋ぎ方**: サブプロセス起動のMCPサーバーは`MCPServerStdio`、常駐サービスとして立てる場合は`MCPServerStreamableHTTP`(SSEより現行の推奨トランスポート)。あとpydantic-aiはMCPの**sampling**(MCPサーバー側がPolarisのモデル設定を借りてLLM呼び出しできる、サーバー側に個別APIキーが不要になる)と**elicitation**(tool実行中に人間へ構造化入力を求める、「送信前に確認」のような用途)にも対応している。ただしelicitationの下位プロトコルは2026-07-28のMCP仕様改定で仕組みが変わった(旧back-channel方式が廃止され、request/resubmit方式に)ばかりなので、使う際はpydantic-ai側の対応状況を都度確認する
- **参考**: Cowork(Claude)自身が今使っているCalendar/Gmail/Drive MCPのtool粒度(list/search/get + create/update/delete + ドメイン固有動詞)は、Polaris側で新しいtool群を設計する際の参考になる

### MCP vs 自前adapter、どちらで実装するか

pydantic-aiはMCP client(toolset)に対応しているため、「良質な既存MCPサーバーがあるもの」(Web検索・カレンダー・メール等の汎用インフラ系)は自前でadapterを書かず、既存MCPサーバーをtoolsetとして繋ぐ方がコスパがいい(個人開発で管理対象を増やしたくない、というSQLite一本化などこれまでの判断と同じ考え方)。一方EDINET/arXivのようにPolaris独自のデータモデル(Hub/Satellite、冪等性chekc等)に深く結びつく取り込みロジックは、既存MCPがあっても結局自前adapter(`adapters/edinet/client.py`等)に落ち着きそう。tool追加時にどちらのパターンかを都度判断する。
