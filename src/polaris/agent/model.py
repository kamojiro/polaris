"""LLM モデルの組み立て."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider

if TYPE_CHECKING:
    from polaris.settings import Settings


def build_model(settings: Settings, *, model_id: str | None = None) -> OpenRouterModel:
    """設定値から OpenRouter 経由のモデルを組み立てる.

    モデル選択は設定値の切替のみで行い、コードに埋め込まない(constitution 参照)。
    `model_id` を指定すると `settings.llm.model_id`(メインのチャット用)の代わりにそちらを使う
    (017-chat-memoryの想起のような、軽量モデルで十分な狭いタスク用)。

    `settings.llm.openrouter_ignore_providers` が空でなければ、OpenRouterのprovider routingで
    そのプロバイダを除外する(LLMSettings.openrouter_ignore_providersのdocstring参照。
    tool呼び出し後にストリーミングがハングする不具合の対処、2026-08-30)。
    """
    provider = OpenRouterProvider(api_key=settings.llm.api_key)
    model_settings: OpenRouterModelSettings = {}
    if settings.llm.openrouter_ignore_providers:
        model_settings["openrouter_provider"] = {"ignore": settings.llm.openrouter_ignore_providers}
    return OpenRouterModel(
        model_id or settings.llm.model_id, provider=provider, settings=model_settings or None
    )
