# チャットエージェントの全体像

ADR-0014の改訂(2026-09-13)で例外的に常設ドキュメント化した1枚。個別アクション(特定のツール1回分の詳細な呼び出し順など)はここには含めない — それは引き続き使い捨てで、必要になった都度その場でMermaidシーケンス図を出す運用のまま(ADR-0014 項目3参照)。ここに書くのは「チャットエージェント」という機能そのものの骨格、つまり①1ターンの処理パイプライン(ADR-0003)と②tool登録の仕組み(ADR-0013)の2つだけ。

この2つは実装済みの決定事項(ADR-0003/0013)に基づいており、変更頻度が低い(`api/app.py`の`chat()`関数の段構成自体や、`agent/chat_agent.py`のtool集約の仕組みは、個々のtoolが増減しても骨格は変わらない)。ただし完全な鮮度保証は無いので、大きな構成変更をしたら描き直すこと(`docs/erd.md`のような自動生成ではない、手動更新の文書)。

## ① 1ターンの処理パイプライン(ADR-0003、`POST /api/chat`)

```mermaid
sequenceDiagram
    participant FE as フロントエンド
    participant API as api/app.py::chat()
    participant Mem as services.memory (想起)
    participant AGUI as AGUIAdapter
    participant Agent as _agent (build_chat_agent)
    participant BG as バックグラウンドタスク

    FE->>API: POST /api/chat (AG-UI RunAgentInput)
    Note over API: 前処理(同期)
    API->>Mem: recall_memory(直近のユーザー発言)
    Mem-->>API: deps.recalled_memory

    Note over API: メイン処理
    API->>AGUI: dispatch_request(agent=_agent, deps, on_complete)
    AGUI->>Agent: agent.run(...)(登録済みtoolを自律的に呼び出す)
    Agent-->>AGUI: AgentRunResult

    Note over API: 後処理(on_complete、ストリーム完了前に呼ばれる)
    AGUI->>API: on_complete(result)
    API->>FE: usage/tool_timings イベント
    API->>FE: MESSAGES_SNAPSHOT(ADR-0012、古い全文結果のトリミング)
    API->>FE: StateSnapshotEvent(論文モード等のstate同期)
    API->>BG: asyncio.create_task(記憶抽出、017-chat-memory)
    Note right of BG: fire-and-forget(結果を待たない)
    alt 日記モード中(state.diary_mode)
        API->>API: await 日記記録(019-diary-domain)
        Note over API: fire-and-forgetにしない(フロントが直後に<br/>執筆中パネルを取り直すため、書き込み完了を保証する)
    end
    API-->>FE: ストリーム完了
```

要点(2026-09-13時点の`api/app.py::chat()`と一致):

- **前処理は同期**: 記憶想起(`recall_memory`)はメインのエージェント実行より前に必ず完了させ、`deps.recalled_memory`としてメイン処理に渡す
- **メイン処理は不変**: `_agent`(`build_chat_agent()`で組み立て済み)をそのまま`AGUIAdapter.dispatch_request`に渡すだけ
- **後処理内でも同期/非同期が混在する**: 記憶抽出(017)は結果を即座に必要とするUIが無いため`asyncio.create_task`でfire-and-forget。日記記録(019)は逆に、フロントがストリーム完了直後にDBを読みに行く設計のため`await`して書き込み完了を保証してから返す(レースコンディション回避、`_record_diary_task`のdocstring参照)

## ② tool登録の仕組み(ADR-0013、`agent/chat_agent.py`)

```mermaid
flowchart LR
    subgraph domain["agent/tools/&lt;domain&gt;.py(ドメインごとに1ファイル)"]
        paper["paper.py<br/>save_paper/list_papers"]
        paper_qa["paper_qa.py<br/>get_paper_full_text/exit_paper_mode"]
        paper_research["paper_research.py<br/>research_related_papers"]
        todo["todo.py<br/>TODOの読み書き"]
        news["news.py<br/>list_news"]
        ir["ir.py<br/>IR文書"]
        diary["diary.py<br/>日記モード"]
        memory["memory.py<br/>動的instructions"]
        web_search["web_search.py<br/>web_search"]
    end

    domain -->|"各モジュールのINSTRUCTIONS文字列"| concat["chat_agent.py: _INSTRUCTIONS<br/>(全ドメイン分を連結)"]
    domain -->|"各モジュールのregister(agent, ...)"| build["build_chat_agent()"]
    concat --> build
    build --> agent["Agent[ChatDeps, str]<br/>(pydantic-ai)"]
```

要点:

- **1ドメイン1ファイル**が規約(`agent/tools/<domain>.py`)。各ファイルが持つのは (a) tool関数本体、(b) LLMに渡す`INSTRUCTIONS`文字列(モジュール定数)、(c) 必要なら`@agent.instructions`の動的instructions関数
- `chat_agent.py::build_chat_agent()`は薄い集約役に徹する: 全ドメインの`INSTRUCTIONS`を連結して`Agent`を1つ作り、各ドメインの`register(agent, ...)`を呼ぶだけ
- toolを1つ追加するときに触る箇所は3つだけ: 新規`tools/<domain>.py`・`chat_agent.py`のimport行・`_INSTRUCTIONS`連結と`register`呼び出し
- `@agent.tool_plain`(depsに触れない)と`@agent.tool`(`RunContext[ChatDeps]`経由でstateを読み書きする、例: 論文モードの`active_paper`)の使い分けは各ドメインファイル側の判断

現在登録されているドメイン(2026-09-13時点、`agent/chat_agent.py`参照): `memory`・`paper`・`todo`(読み書き分離)・`paper_qa`・`paper_research`・`web_search`・`news`・`ir`・`diary`、加えてpydantic-ai同梱の`web_fetch_tool()`。

## ③ 現在登録されているtool一覧(2026-09-13時点)

LLMから見える`@agent.tool`/`@agent.tool_plain`関数のみ(`@agent.instructions`の動的instructions関数は挙動を変えるだけでtoolとしては呼ばれないため、ここには含めない)。役割の文はコード側のdocstring1行目そのまま(LLMにもそのまま渡る説明文)。

| ドメイン(`agent/tools/`) | tool | 種別 | 役割 |
| --- | --- | --- | --- |
| `paper.py` | `save_paper` | plain | arXiv/PDF直リンクURL/アップロード済みPDFからメタデータ・本文を取得し、チャンク分割まで行って保存する |
| `paper.py` | `list_papers` | plain | 保存済みの論文一覧を直近分だけ返す(総件数も併せて返す) |
| `paper_qa.py` | `get_paper_full_text` | tool(state) | 保存済み論文の本文全文を取得し、会話に取り込む(論文モードに入る) |
| `paper_qa.py` | `exit_paper_mode` | tool(state) | 論文モードを終了する |
| `paper_research.py` | `research_related_papers` | tool(state) | 論文を起点に引用チェイニングで関連論文を集める調査を、キューに1件追加する(027) |
| `todo.py` | `add_todo` | plain | 新しいTODOを追加する |
| `todo.py` | `list_todos` | plain | TODO一覧を返す(既定では未完了のみ、熟成度順) |
| `todo.py` | `update_todo` | plain | 既存TODOのタイトル・詳細メモ・時間スケールを更新する |
| `todo.py` | `complete_todo` | plain | TODOを完了にする |
| `todo.py` | `delete_todo` | plain | TODOを削除する(物理削除) |
| `news.py` | `list_news` | plain | 取り込み済みのニュース記事一覧を返す(情報源ラベルごとにグルーピング表示) |
| `ir.py` | `save_ir_document` | plain | EDINETのdocIDからIR文書(有価証券報告書等)のPDFを取得し保存する |
| `ir.py` | `list_ir_documents` | plain | 保存済みのIR文書一覧を直近分だけ返す |
| `ir.py` | `get_ir_full_text` | plain | 保存済みIR文書の本文全文を取得し、会話に取り込む |
| `diary.py` | `get_diary_range` | plain | 指定期間の日記エントリを返す |
| `diary.py` | `set_diary_mode` | tool(state) | 日記モードを開始/終了する(019) |
| `web_search.py` | `web_search` | plain | Webを検索する(最新情報や、保存済みデータには無い一般的な事柄を調べる) |
| `memory.py` | (toolなし) | — | `_memory_instructions`のみ登録(想起結果を動的instructionsとして差し込む、toolとしては何も公開しない) |
| (chat_agent.py直接) | `web_fetch` | pydantic-ai同梱 | 具体的なURLの内容を直接取得する(SSRF対策済み、SearXNGでの近似ではなく直接読ませたいときに使う) |

「tool(state)」は`RunContext[ChatDeps]`経由で論文モード/日記モードのstateを読み書きするtool、「plain」は`@agent.tool_plain`(depsに触れない)。

## 関連

- ADR-0003(チャットターンの3段パイプライン)、ADR-0012(このドキュメントの後処理段が触れる履歴トリミング)、ADR-0013(tool登録のドメイン分割)
- `ARCHITECTURE.md`(C4図、`agent`コンテナが`services`/`adapters`をどう呼ぶかという層構造の全体像)
