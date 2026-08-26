"""アプリケーション設定."""

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    """LLM(OpenRouter)接続設定.

    モデル選択は設定値の切替のみで行い、コードに埋め込まない(constitution 参照)。
    開発フェーズは無料枠の Qwen3-30B-A3B、本番フェーズは Qwen3.6-35B-A3B を想定。
    """

    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    model_id: str = "qwen/qwen3-30b-a3b:free"


class IngestSettings(BaseModel):
    """論文 Ingest パイプライン(002-papers-ingest-full)の設定.

    Embedding モデルは ADR-0001 / spec.draft.md で決定済み(Qwen3-Embedding-0.6B、
    sentence-transformers 経由でローカルロード)。チャンク分割の粒度は未確定のため、
    設定値で調整できるようにしておく。
    """

    pdf_dir: str = "data/pdfs"
    embedding_model_id: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dim: int = 1024
    chunk_chars: int = 1200
    chunk_overlap_chars: int = 200
    # 014-paper-url-pdf-ingest: URL直リンク・ローカルPDFの取り込み用設定。
    upload_dir: str = "data/uploads"
    max_pdf_bytes: int = 50_000_000
    # 非arXiv論文のメタデータ抽出(agent/extract_metadata.py)に渡す本文先頭の文字数。
    # 長すぎるとプロンプトが肥大化するだけなので、書誌情報が載っている冒頭のみで十分。
    metadata_head_chars: int = 4000


class ChatSettings(BaseModel):
    """チャットエージェント本体(agent/chat_agent.py)の設定(015-paper-qa-chat)."""

    # 実測: 保存済み論文の抽出全文は 35k〜151k 文字。200k(≒57kトークン)なら
    # 現行モデル(Qwen3-30B-A3B: 131K コンテキスト)に収まり、実データ全件をカバーできる。
    max_full_text_chars: int = 200_000
    # チャットUIのコスト表示(USD→JPY)用の固定為替レート。為替APIは個人用ツールには
    # 過剰なため呼び出さず、相場が動いたら手動でこの値を更新する運用にする。
    usd_jpy_rate: float = 159.0


class SearxngSettings(BaseModel):
    """自前ホスト済み SearXNG インスタンスへの接続設定(018-web-search-tool)."""

    # Polarisと同じdocker-composeネットワーク内ならサービス名解決(例: http://searxng:8080)、
    # そうでなければポートマッピング済みのlocalhostを指す想定。
    base_url: str = "http://localhost:8080"
    # 実測: results 1件あたり210〜399文字。10件でも3.2k文字程度だが、他のツールと
    # 共存するチャットのコンテキストを無駄に膨らませないため既定は5件に絞る。
    max_results: int = 5
    timeout_seconds: float = 10.0


class MemorySettings(BaseModel):
    """チャットの長期記憶(017-chat-memory)の設定."""

    # テーマごとの現在状態ファイル(<slug>.md)の保存先。ログ層(MemoryEvent)はDBだが、
    # 会話に読み込ませる実体はこちら(ingest.pdf_dirと同じ「ディレクトリ設定+都度読み書き」パターン)。
    dir: str = "data/memory"
    # 想起(前処理、毎ターン同期呼び出し)専用のモデル。短いユーザー発言をテーマ索引の
    # 短い説明文と照合するだけの単純な分類タスクのため、メインのチャットモデル
    # (llm.model_id)より軽量なモデルで十分と判断し、明示的に分離できるようにした
    # (2026-08-26)。Qwen3-8B は131Kコンテキストで低コスト、この用途には過剰なほど軽い。
    recall_model_id: str = "qwen/qwen3-8b"


class NewsFeed(BaseModel):
    """1件のRSS/Atomフィード設定(008-daily-digest-domain Phase A)."""

    name: str
    url: str
    label: str  # source_label(対立軸の定義方針、spec参照)。フィード単位で静的に決まる


class NewsSettings(BaseModel):
    """RSS Ingest(008-daily-digest-domain Phase A)の設定.

    既定のフィード一覧はspecで実機確認済みのもの(2026-08-26)。ニュースレター系
    (Ahead of AI等)・非公式ミラー系(HF Papers等)はspecが明記した運用リスク
    (ミラー停止で静かに壊れる)により既定からは除外している。必要になれば
    ここに追加するだけでよい。
    """

    feeds: list[NewsFeed] = [
        # ai_llm
        NewsFeed(
            name="arXiv (cs.LG+cs.AI+cs.MA+cs.IR)",
            url="https://rss.arxiv.org/rss/cs.LG+cs.AI+cs.MA+cs.IR",
            label="ai_llm",
        ),
        NewsFeed(name="Simon Willison", url="https://simonwillison.net/atom/everything/", label="ai_llm"),
        # swe_general
        NewsFeed(name="arXiv (cs.SE)", url="https://rss.arxiv.org/rss/cs.SE", label="swe_general"),
        NewsFeed(name="Martin Fowler", url="https://martinfowler.com/feed.atom", label="swe_general"),
        NewsFeed(name="InfoQ", url="https://www.infoq.com/feed/", label="swe_general"),
        NewsFeed(
            name="The Pragmatic Engineer", url="https://newsletter.pragmaticengineer.com/feed", label="swe_general"
        ),
        NewsFeed(name="Julia Evans", url="https://jvns.ca/atom.xml", label="swe_general"),
        NewsFeed(name="the morning paper", url="https://blog.acolyer.org/feed/", label="swe_general"),
        # jp_tech_blog
        NewsFeed(name="Zenn トレンド", url="https://zenn.dev/feed", label="jp_tech_blog"),
        NewsFeed(name="Qiita トレンド", url="https://qiita.com/popular-items/feed", label="jp_tech_blog"),
        NewsFeed(
            name="はてなブックマーク テクノロジー", url="http://b.hatena.ne.jp/hotentry/it.rss", label="jp_tech_blog"
        ),
        # tech_industry_news
        NewsFeed(name="Hacker News (hnrss)", url="https://hnrss.org/frontpage", label="tech_industry_news"),
    ]
    # 1フィードあたりの取り込み上限(暴走防止。はてブ等は大量に流れてくるため)。
    max_entries_per_feed: int = 20
    timeout_seconds: float = 15.0


class Settings(BaseSettings):
    """アプリケーション全体の設定.

    `.env` ファイルおよび環境変数(`LLM__` / `INGEST__` プレフィクスでネスト)から読み込む。
    """

    DB_PATH: str = "data/polaris.db"
    LOG_LEVEL: str = "INFO"
    LOG_PATH: str = "data/polaris.log"
    # Embeddingのバッチ進捗・GPUメモリ診断ログはリクエストごとに数十行出て他のログに
    # 埋もれやすいため、専用ファイルに分けて追いやすくする(コンソール/LOG_PATHにも引き続き出る)。
    GPU_LOG_PATH: str = "data/gpu.log"

    llm: LLMSettings = LLMSettings()
    ingest: IngestSettings = IngestSettings()
    chat: ChatSettings = ChatSettings()
    searxng: SearxngSettings = SearxngSettings()
    memory: MemorySettings = MemorySettings()
    news: NewsSettings = NewsSettings()

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )
