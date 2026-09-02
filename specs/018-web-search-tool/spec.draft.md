# 018. Web検索tool(SearXNG連携)

## ステータス

✔️ 完了

## 概要

チャットエージェント(および将来の前処理/後処理パイプライン)から使える汎用Web検索toolを追加する。自前ホスト済みのSearXNGインスタンスを検索バックエンドとして使う。接続方式はMCPではなく**自前のHTTPクライアント(adapter)**にする(2026-08-23、方針転換。詳細は背景・判断参照)。

## 背景・判断

- 汎用Web検索は複数ドメインから必要とされている: 論文ドメインのセレンディピティ的発見、`007-todo-domain`が将来spec扱いにした現況調査エージェント、`013-ir-analysis-domain`の企業背景確認、`017-chat-memory`の想起・抽出まわりなど。1つ作れば複数specの前提を同時に満たせるため優先度を上げる(`specs/IDEAS.md`参照)
- SearXNGは既に自前ホスト済みで運用中なので、追加のサードパーティ依存・APIキー契約は不要
- **接続方式の再検討(2026-08-23)**: 当初はMCP toolset経由(`SecretiveShell/MCP-searxng`等)を想定していたが、方針転換した。SearXNGの検索エンドポイントは`GET /search?q=...&format=json`1本・認証不要という単純なAPIで、MCPサーバー(サードパーティのサブプロセス、単一メンテナのお守りリスクがある)を挟むメリットが薄い。`adapters/arxiv/client.py`/`adapters/edinet/client.py`と同じ形で`adapters/searxng/client.py`に`httpx`呼び出し1つを書く方が、依存を増やさずシンプルに済む
- これに伴い、`specs/IDEAS.md`の「MCP vs 自前adapter」の判断基準も「汎用インフラ系かどうか」から「APIの複雑さ・信頼できる実装の有無」に整理し直した(`specs/IDEAS.md`参照)。Google Calendar/Gmail(OAuth・複数エンドポイント・複雑なデータ構造、かつ公式MCPがある)はMCP側、SearXNG(単純なGET1本)は自前adapter側、という切り分けになる

## tool設計

- チャットエージェントに`web_search(query)`toolを1つ追加する。`adapters/searxng/client.py::search(query) -> list[SearchResult]`を薄くラップする
- 複数クエリを並列に投げたいユースケース(017の想起判定、007の現況調査等)が具体化したら、`asyncio.gather`で複数リクエストを並列実行すればよい(MCPサーバーを並列対応実装に差し替える必要はない)

## 接続方式

自前adapter(`adapters/searxng/client.py`)による直接HTTP呼び出し。`httpx`で`GET {settings.searxng_url}/search?q=...&format=json`を叩き、結果をパースして返す。MCPは使わない。

SearXNGはコンテナで運用中。`settings.searxng_url`は環境に応じて、Polarisと同じdocker-composeネットワーク内なら`http://searxng:<port>`(サービス名解決)、そうでなければポートマッピング済みの`http://localhost:<port>`を指す想定。追加のプロセス(MCPサーバー等)を挟まないぶん、コンテナ構成もシンプルなまま(SearXNGコンテナ+Polarisコンテナ/プロセスの2者間HTTPのみ)。

## 利用箇所(想定、具体的な組み込みは各specで判断)

- `007-todo-domain`(将来spec: 現況調査エージェント)
- `013-ir-analysis-domain`(企業背景の補助情報取得)
- `017-chat-memory`(想起・抽出の判断材料としての間接利用、将来拡張)
- 論文ドメインのセレンディピティ的発見(具体spec未定)

## 実装状況(2026-08-24)

- `adapters/searxng/client.py`: `search(query, *, client, base_url, max_results, timeout_seconds) -> SearxngResponse`。`GET {base_url}/search?q=...&format=json`を叩き、`SearchResult`/`Answer`/`Infobox`をpydanticでパースする。HTTP失敗は`SearxngSearchError`に包んで送出
- `chat_agent.py`: `_register_web_search_tools()`で`web_search(query)`を`@agent.tool_plain`として登録。`_format_search_results()`で「エンジンの回答→関連情報→検索結果一覧」の順に整形した文字列を返す(generative UI化はせず、`get_paper_full_text`と同じ「整形済み文字列を返すだけ」の方針)
- `settings.py`: `SearxngSettings(base_url="http://localhost:8080", max_results=5, timeout_seconds=10.0)`を追加
- `_INSTRUCTIONS`に、保存済みデータ(論文/TODO)についての質問にはweb_searchを使わずlist_papers/get_paper_full_text/list_todosを使うよう明記(ツールが9個になったための誤爆防止)
- テストは`adapters/searxng/client.py`のみ(`tests/adapters/test_searxng_client.py`、respxでモック)。フィクスチャ`tests/adapters/fixture_searxng.json`は実機のSearXNG(`http://127.0.0.1:8080`)に実際にクエリを投げて取得した本物のレスポンス。chat_agent.py側のツールは既存方針どおりユニットテスト対象外(agent層は手動E2Eで担保)
- E2E検証(実LLM、実SearXNG): (1) ブラウザから「SearXNGって何?最近の話題も含めて調べて」→ `web_search`が呼ばれ、出典URL付きの回答が返ることをブラウザ・バックエンドログの両方で確認。(2) 「保存した論文は?」で`web_search`ではなく`list_papers`が呼ばれる(誤爆しない)ことを、下記の既存バグの影響を受けない`agent.run()`直接呼び出しで確認(出力が`list_papers`成功時の定型文と一致)。(3) SearXNGコンテナを`docker pause`で一時停止した状態で`web_search`を呼び、`SearxngSearchError`が握りつぶされずに「検索に失敗しました」という日本語メッセージとしてユーザーに返ることを確認(`agent.run()`経由)

### 実機調査で判明した事実(実装前の実測、`base_url=http://127.0.0.1:8080`)

- `number_of_results`は常に`0`が返る(SearXNGでよくある挙動)。件数として信用できないため、レスポンスモデルに含めていない。件数は`len(results)`を使う
- `results`は既に`score`降順でソート済み。1件あたりのスニペットは実測210〜399文字、10件合計で約3,200文字(≒1kトークン強)
- `answers`(検索エンジンのinstant answer)・`infoboxes`(Wikipedia等の要約)は情報密度が高く、コストもほぼゼロなので出力に含めている
- 日本語クエリも`language=ja`等のパラメータ無しで正常動作する(v1は`query`のみ使用)

### E2E検証で見つかった、018とは無関係の既存バグ

手動E2E中に、ブラウザから「保存した論文は?」(list_papers誘発)を送ると`/api/chat`のSSEストリームが応答を返さず無限にハングする現象を発見した。調査の結果:

- `agent.run()`(非streaming)は毎回正常・高速(3秒程度)に完了する。ハングするのは`AGUIAdapter.dispatch_request`が内部で使う`agent.run_stream_events()`(streaming)経由のときだけ
- ストリームイベントを直接覗くと、`list_papers`(引数無し)のツール呼び出しで`PartStartEvent(ToolCallPart(args=''))` → `PartDeltaEvent(args_delta='')`の直後に後続イベントが一切来ずハングする。**引数を1つ以上取るツール(`web_search`含む)では発生しない**
- `git stash`で018の変更を完全に外したorigin/main(`0227e0f`)でも同じ手順(`agent.run_stream_events()`を直接呼ぶ)で再現した(4回中3回ハング)。よって**018が原因ではなく、`qwen/qwen3-30b-a3b:free`(OpenRouter無料枠)がツール呼び出しの空引数(`args=''`)をストリーミングで送ってきた際、pydantic-ai側がその完了を検知できず待ち続ける、既存の潜在バグ**と判断した(non-deterministicで、モデル側のストリーミング実装の揺れに起因すると見られる)
- `list_papers`/`list_todos`/`exit_paper_mode`など、引数無し(または全省略可能)で呼ばれうる既存ツールすべてに影響しうる。018のE2E検証は、このバグの影響を受けない`agent.run()`(非streaming)経由での確認に切り替えて実施した(下記参照)
- このバグ自体の修正(pydantic-ai側のツール呼び出し完了検知ロジックの調査、または全ツールに`ctx`等のダミー引数を持たせる回避策の検討)は018のスコープ外とし、別途対応が必要な既知の問題として記録するに留める

## 未決定事項

- チャットエージェントに常時toolとして持たせる方針で実装した(v1では必要なドメインだけに絞る運用はしていない)。ツール数が増えて誤爆が目立つようになったら`filtered`等での絞り込みを検討する
- **実例(2026-09-01)**: 「9月3,4,5,6日の大阪駅あたりの天気予報を教えて」(URLを含まない一般的な質問)に対し、`web_search`ではなく`web_fetch`が呼ばれ、`Tool 'web_fetch' exceeded max retries count of 1`で失敗した。URLがメッセージに存在しないため、モデルが天気サイトのURLを自己推測して`web_fetch`に渡したと見られる(天気系サイトはJSレンダリングの動的ページが多く、`web_fetch`の生HTTP取得では中身を取れず失敗しやすい)。`web_fetch`のリトライ上限を上げるのは対症療法(誤ったtool選択自体を繰り返すだけ)で根治にならない。対策候補: `_INSTRUCTIONS`に「web_fetchのurl引数は、ユーザーの入力または会話履歴に実際に登場した文字列そのものに限る。自分でURLを推測・生成して渡してはいけない。URLが無い一般的な質問には必ずweb_searchを使うこと」のような明示的な禁止指示を追記する。まだ1回の観測のみで、011が着手トリガーとする「LLMのtool選択精度の恒常的な低下」と呼べるほどの頻度ではないため、次に同種の誤爆が見られたら本格対応(instructions修正)を検討する
- 検索結果は`settings.searxng.max_results`(既定5件)で絞っている。実測では10件でも問題ないため、必要になれば増やせる
- `answers`/`infoboxes`のURLが空の場合の表示(現状は出典表記を省略するだけ)

## 依存

- 特になし(SearXNGインスタンスは運用中)
