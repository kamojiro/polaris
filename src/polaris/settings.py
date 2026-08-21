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
    usd_jpy_rate: float = 150.0


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

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )
