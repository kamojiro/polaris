"""LLM モデルの組み立て."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

if TYPE_CHECKING:
    from polaris.settings import Settings


def build_model(settings: Settings) -> OpenRouterModel:
    """設定値から OpenRouter 経由のモデルを組み立てる.

    モデル選択は設定値の切替のみで行い、コードに埋め込まない(constitution 参照)。
    """
    provider = OpenRouterProvider(api_key=settings.llm.api_key)
    return OpenRouterModel(settings.llm.model_id, provider=provider)
