# アイデア置き場

まだspecにするほど固まっていない、作業中に思いついたことのメモ。specの体裁(概要・受け入れ条件など)を整える手前の雑多な置き場なので、書式は問わない。着手する気になったら該当specへ書き足す(無ければ新規spec化する)か、`specs/README.md`の一覧に載せる。

## 既知の不具合(未対応)

- **AG-UIの`TEXT_MESSAGE_CONTENT`イベントで"No active text message found"エラー**(2026-08-31発見、未再現・未解決): 通常のチャット中(日記モード等の特定モードではない)に、フロント(`@ag-ui/client`の`HttpAgent`)が`Cannot send 'TEXT_MESSAGE_CONTENT' event: No active text message found with ID '<uuid>'. Start a text message with 'TEXT_MESSAGE_START' first.`というエラーを出したという報告。これは`@ag-ui/client`側のプロトコル整合性チェック(`TEXT_MESSAGE_START`で開始していないメッセージIDへの`TEXT_MESSAGE_CONTENT`を拒否する)で、サーバー側(`pydantic_ai.ui.ag_ui._event_stream.AGUIEventStream`、`.venv`内のライブラリコード、Polaris自前のコードではない)が送るイベント列の順序不整合が原因と見られる。

  `AGUIEventStream.before_response()`は「後続のモデル応答のpartが以前の応答のpartに紐付かないように」という理由(pydantic-ai issue #3316参照とコード内コメントにあり)で、ModelResponseが切り替わるたびに`new_message_id()`でメッセージIDをリセットしている。1ターン内でtool呼び出し→最終テキストのように複数のModelResponseにまたがる場合や、ストリーム再試行が絡む場合に、クライアント側が既に閉じた(またはまだ開始していない)メッセージIDへ`CONTENT`が送られる余地がありそうだが、詳細な発生条件はまだ特定できていない。

  調査時点でのメモ: (a) 発生時は日記モードではなく通常のチャット中だったとの報告、(b) 同日実施した`ADR-0013`のchat_agent.py分割(`_INSTRUCTIONS`文字列のハッシュ一致を確認済み、ストリーミング経路自体は無変更)や日記rewriter修正はこの経路に触れていないため無関係と考えられる、(c) ライブブラウザでTODO一覧・論文一覧・日記モード切り替えを試したが再現しなかった。再発時は送信した具体的なメッセージ内容・直前のtool呼び出しの有無(あれば何のtool)をメモしてもらえると原因切り分けの手がかりになる。
- **論文QAで全文コンテキスト方式がmodel token limitに引っかかる(2026-09-01発見)**: `015-paper-qa-chat`の`get_paper_full_text`(ADR-0009の全文インコンテキスト方式)で論文について質問した際、OpenRouterの「Model token limit (provider default) exceeded」エラーに遭遇。原因未特定。2つの可能性が考えられる: (a) 同種のエラー文言は以前「チャット履歴がツール結果を積み上げ続ける」問題(ADR-0012で対応済み、下記「解決済みの不具合」参照)でも見られたもので、そちらの修正がまだ実機に反映されていない(git pull/再起動未了)だけの可能性、(b) ADR-0012は履歴内の**古い**`ToolReturnPart`しかトリミングしないため、単発でも特に大きい1論文の全文(+システムプロンプト+会話の他の部分)だけで`provider default`のトークン上限を超えるケース(ADR-0012の対象外)。再現時の状況(論文の大きさ、会話がどれだけ長かったか、ADR-0012適用後の環境かどうか)を控えておくと切り分けやすい

## 解決済みの不具合

- **toolのstreaming時ハング**(2026-08-24発見 → 2026-08-30解決): `AGUIAdapter`のstreaming経路(`agent.run_stream_events()`)で、tool呼び出しの引数をモデルがストリーミングし終えた(はずの)直後に後続イベントが来ずSSEが無限にハングする不具合。`018-web-search-tool`のE2E検証中に`list_papers`(引数無し)で発見し、origin/main(018の変更を含まない状態)でも4回中3回再現したため018固有の問題ではないと確認していた。2026-08-25に実運用中`save_paper(url=...)`(引数**あり**)でも同じ症状(openrouterからの応答は届いているのに`tool call: save_paper(...)`のログが出ないまま数分単位で無反応)を確認し、引数の有無に限定された問題ではないと分かっていた。2026-08-27には`list_news`(引数無し)のE2E確認中4回中4回再現し、再現率の悪化も観測されていた。

  **原因調査(2026-08-30)**: `pydantic_ai.Agent.run_stream_events()`を直接叩く最小再現(zero-arg toolを1つ持つだけのエージェント)で5回中2回ハングを再現。イベント列を見ると、`ToolCallPart(args='')`開始 → 空の`ToolCallPartDelta(args_delta='')` → **そのまま何も届かない**、というパターンで停止していた(成功時は続けて`args_delta='{'`→`'}'`が届き`PartEndEvent`で閉じる)。pydantic-aiのバグを疑い、openai SDKを経由せず`httpx`で生のSSEを直接叩いて検証したところ、**OpenRouterのゲートウェイ自体が`: OPENROUTER PROCESSING`というキープアライブのコメント行を約0.42秒間隔で送り続けている**ことが判明。これによりhttpxの読み取りタイムアウトは毎回リセットされ、クライアント側からは接続が生きているように見えたまま、上流の推論プロバイダ側では実際には生成が完全に停止している(壁時計タイムアウトを別途かけないと検知できない)。生SSEレスポンスの`provider`フィールドを見ると、ハングした試行は**6回中6回とも`AkashML`**というOpenRouterのプロバイダ経由だった。OpenRouterのprovider routing機能(`provider.ignore`)で`AkashML`を明示的に除外して再検証したところ、別プロバイダ(`Parasail`)に固定でルーティングされ、8回中8回とも1〜4秒でクリーンに完了・ハング0件だった。

  **対応**: pydantic-ai/自前コードの不具合ではなく、OpenRouter上の特定プロバイダ(`AkashML`)がこのモデル(`qwen/qwen3.6-35b-a3b`)のtool呼び出し生成を高頻度(実測60%程度)でスタックさせるインフラ側の問題と特定。`src/polaris/settings.py`の`LLMSettings.openrouter_ignore_providers`(既定値`["AkashML"]`)を`src/polaris/agent/model.py::build_model()`で`OpenRouterModelSettings(openrouter_provider={"ignore": [...]})`として全エージェント共通のモデル設定に反映することで解消した。ユニットテストは`tests/agent/test_model.py`。他のOpenRouterプロバイダでも将来同種の問題が起きうる点は変わらないため、application-level(`/api/chat`側)のタイムアウト+リトライという安全網は別途検討の余地あり(このspecでは未着手)。
- **チャット履歴がツール結果を積み上げ続け、コンテキスト上限に達する**(2026-08-29発見 → 2026-08-30解決): 「Model token limit (provider default) exceeded before any response was generated」というOpenRouterのエラーに遭遇(有料モデル`qwen/qwen3.6-35b-a3b`使用時、`.env`の`LLM__MODEL_ID`で確認済みなので無料枠固有の問題ではない)。コードを追って原因を特定した: ADR-0005の設計どおりサーバーはステートレスで、フロントの`HttpAgent`(`@ag-ui/client`)がブラウザ側で累積メッセージ履歴を保持し、チャットターンごとに丸ごと`/api/chat`へ送信する。この往復で`ToolReturnPart`(ツール呼び出し結果)は一切トリミングされず完全に往復する(pydantic-ai `ui/ag_ui/_adapter.py`の`dump_tool_return_content`/`rehydrate_tool_return_content`)。つまり`get_paper_full_text`(実測131,484文字≒3.7万トークン相当)や`web_fetch`の結果、将来`013-ir-analysis-domain`で扱うIR文書全文(論文よりさらに長大になりうる)を一度ツール経由でコンテキストに入れると、その内容は同じセッション内の以降の全ターンで毎回まるごと再送信され続け、コンテキストが単調増加する。`015-paper-qa-chat`の受け入れ条件(`spec.draft.md:110`)は「2ターン目で`get_paper_full_text`を再度呼ばず会話履歴の全文で回答すること」であり、1論文に集中する分には意図した設計だが、セッションが長引いて複数の論文/IR文書/web_fetch結果が同じ履歴に積み重なるケースは想定されていない。pydantic-aiには`CompactionPart`というプロバイダーネイティブの圧縮機構もあるが、Anthropic/OpenAI専用でOpenRouter経由のQwen系には使えない(`supports_cache_control`と同様の制約)。

  **対応(2026-08-30実装完了)**: `docs/adr/0012-trim-stale-tool-results-from-history.md`で設計、`src/polaris/services/history_trim.py`(`FULL_TEXT_TOOL_NAMES`)+`api/app.py`の`on_complete`で実装。対象toolの`ToolReturnPart`のうち履歴内で一番新しいもの1件だけ残し(item_id照合は不要、tool_nameと出現順序だけで判定)、他は`<omitted ...>`形式のプレースホルダに置換、`MessagesSnapshotEvent`でクライアント側の履歴自体を書き換える。冪等な再取得で情報は失われないため、embedding復活(ADR-0011)は不要。`019-diary-domain`の`get_diary_range`にも同じ仕組みを適用済み(`FULL_TEXT_TOOL_NAMES`に追加)。`web_fetch`/`web_search`のように「今アクティブな1件」という概念が無いtoolの扱いは未設計のまま残っている。

  **注意(2026-08-31追記)**: 同一のエラー文言("Model token limit (provider default) exceeded...")が、これとは**別の原因**でも再現することを確認した。詳細は`specs/019-diary-domain/research.md`のDecision 10/11参照: 対応手段(tool)の無いユーザー要求に対してreasoning有効なモデルが延々と思考し続け、コンテキスト(入力)ではなく**1ターンの完了トークン予算(reasoning + 出力)**をreasoningだけで使い切ってしまうケース。同じエラー文言でも「コンテキストが大きすぎる」パターンと「reasoning予算を使い切った」パターンの少なくとも2種類の原因があるため、再発時はどちらか(あるいは他の原因か)を都度切り分けること。後者への対応は「モデルに実際の対応手段を与える(hallucinated capabilityの防止)」+「`OpenRouterModelSettings`で`max_tokens`/`openrouter_reasoning.max_tokens`に明示的な上限を設ける」の組み合わせ
- **Ingestの冪等性チェックがembeddingの有無を見ていない**: `services/ingest_paper.py`の「既にIngest済みなのでスキップ」判定は`repo.list_chunks(item.id)`が非空かどうかだけで判断しており、embedding(sqlite-vecの`embeddings`テーブル)が実際に生成済みかは見ていない。上記のGPU OOM(fp16化で対応済み、`adapters/embeddings/qwen.py`参照)でchunk分割まで終わった直後にEmbedding生成が失敗した場合、chunkだけがDBに残り、以後同じURLを再送しても「既に取り込み済み」として無条件にスキップされ続け、embeddingが永久に欠けたまま(要約も、その失敗した回に生成された古い内容のまま)になる。今回は手動でItem/PaperRecord/Chunkを削除して再送することで復旧した。判定条件をchunk数ではなくembedding数(またはchunk数とembedding数の一致)に変えるのが本来の直し方(2026-08-25)

## 未整理

- **Playwright UIテストの導入は保留(2026-08-30)**: Claude CodeにPlaywright MCPは使える状態にしてあるが、E2Eテストの導入自体は今は見送る。理由は`005-eval-harness`と同じ構造: UIがまだ活発に変化中(003のコピーボタン/モードチップ、008のニュース一覧の見た目の指摘が未反映、等)の段階でDOM構造に対するアサーションを書くと、デザイン変更のたびに壊れて「テストが赤くなるのが嫌でドラスティックな変更を避ける」という逆効果を生みかねない。個人用ツールで自動テストが拾う不具合と自分で気づく不具合の差も大きくない。着手トリガーは「入力欄(composer)・メッセージ一覧という土台部分がドラスティックに変わらなくなったら」。それまでの代替として、UI変更の影響を受けない`services/*.py`のような純粋関数のユニットテストは今すぐ投資しても損しにくい

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
