# アーキテクチャ概要

ADR-0014「ドキュメントの鮮度維持方針」に基づき、更新頻度が低い前提でMermaidのC4図を1枚だけ置く。手動更新の文書なので、大幅な構成変更があったときだけ描き直す(コード変更のたびに追従させる対象ではない)。

コード側の実際の依存関係(どのモジュールがどのモジュールをimportしてよいか)は、この図の「解説」ではなく`pyproject.toml`の`[tool.importlinter]`契約がCIで強制する一次情報。詳細な最新のテーブル定義は`docs/erd.md`(自動生成、ADR-0014)を参照。

## コンテキスト図

Polarisを1つの箱として、ユーザーと外部システムとの関係だけを示す。

```mermaid
C4Context
    title Polaris システムコンテキスト図

    Person(user, "ユーザー", "個人利用者")

    System(polaris, "Polaris", "個人用の知識・生活管理プラットフォーム")

    System_Ext(openrouter, "OpenRouter", "LLM API(チャット・各種エージェント処理)")
    System_Ext(searxng, "SearXNG", "自前ホストの検索エンジン")
    System_Ext(semantic_scholar, "Semantic Scholar", "引用グラフ・論文メタデータAPI")
    System_Ext(arxiv, "arXiv", "論文メタデータ・PDF")
    System_Ext(edinet, "EDINET", "有価証券報告書等の開示書類API")
    System_Ext(discord, "Discord", "チャンネルメッセージ(読み取り専用)")
    System_Ext(rss, "RSS/Atomフィード", "ニュース記事の取り込み元")
    System_Ext(hf, "Hugging Face Hub", "Embeddingモデル配布元(ADR-0011で生成自体は一時停止中)")

    Rel(user, polaris, "ブラウザで利用")
    Rel(polaris, openrouter, "チャット応答・各種エージェント処理を依頼")
    Rel(polaris, searxng, "Web検索")
    Rel(polaris, semantic_scholar, "関連論文調査(引用チェイニング)")
    Rel(polaris, arxiv, "論文メタデータ・PDF取得")
    Rel(polaris, edinet, "IR文書取得")
    Rel(polaris, discord, "メッセージ取得")
    Rel(polaris, rss, "ニュース取り込み")
    Rel(polaris, hf, "Embeddingモデルダウンロード(現在は未呼び出し)")
```

## コンテナ図

Polaris内部の主要コンテナと、`import-linter`で強制している層構造(`cli`/`api` → `agent` → `services` → `adapters`/`db` → `domain`)を示す。`polaris.settings`/`polaris.progress`はどの層からも参照される横断的なユーティリティのため、層構造そのものには含めていない(図でも省略)。

```mermaid
C4Container
    title Polaris コンテナ図(層構造、ADR-0014)

    Person(user, "ユーザー")

    System_Boundary(polaris, "Polaris") {
        Container(frontend, "フロントエンド", "React + Vite", "チャットUI。AG-UI経由でバックエンドと通信")
        Container(api, "api", "FastAPI", "AG-UIチャットエンドポイント・REST API")
        Container(cli, "cli", "Python", "cron駆動のバッチ処理(ニュース取り込み・日次要約・関連論文調査等)")
        Container(agent, "agent", "pydantic-ai", "LLMエージェント(チャット・各種抽出・要約・統合)")
        Container(services, "services", "Python", "ドメインロジック・オーケストレーション")
        Container(adapters, "adapters", "httpx", "外部APIへの薄いラッパー")
        Container(db, "db", "SQLModel", "リポジトリ層(Session操作はここに閉じる)")
        Container(domain, "domain", "SQLModel", "エンティティ定義(Hub/Satelliteパターン、ADR-0004)")
        ContainerDb(sqlite, "SQLite", "data/polaris.db", "唯一の永続化ストレージ(ADR-0001)")
    }

    System_Ext(openrouter, "OpenRouter")
    System_Ext(external_apis, "外部API群", "Semantic Scholar / arXiv / EDINET / Discord / SearXNG / RSS")

    Rel(user, frontend, "ブラウザで利用")
    Rel(frontend, api, "AG-UI / REST(HTTPS)")
    Rel(api, agent, "呼び出す")
    Rel(api, services, "呼び出す")
    Rel(api, db, "呼び出す")
    Rel(cli, agent, "呼び出す")
    Rel(cli, services, "呼び出す")
    Rel(cli, db, "呼び出す")
    Rel(agent, services, "呼び出す")
    Rel(agent, adapters, "呼び出す")
    Rel(services, adapters, "呼び出す")
    Rel(db, domain, "参照")
    Rel(adapters, domain, "参照")
    Rel(db, sqlite, "読み書き")
    Rel(agent, openrouter, "LLM呼び出し")
    Rel(adapters, external_apis, "HTTPS")
```

`adapters`と`db`は互いをimportしない兄弟レイヤー(どちらも`domain`のみに依存する)。`services`は`agent`が定義するProtocol型(`PaperStructurer`等)を型注釈としてのみ参照することがあるが、実行時のimportではないため層構造上の違反ではない(`pyproject.toml`の`ignore_imports`に個別列挙して明示している)。
