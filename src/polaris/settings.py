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


class Settings(BaseSettings):
    """アプリケーション全体の設定.

    `.env` ファイルおよび環境変数(`LLM__` プレフィクスでネスト)から読み込む。
    """

    DB_PATH: str = "data/polaris.db"
    LOG_LEVEL: str = "INFO"

    llm: LLMSettings = LLMSettings()

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )
