"""build_model()のOpenRouter provider routing設定のテスト.

2026-08-30: OpenRouter上でqwen/qwen3.6-35b-a3bを配信する`AkashML`プロバイダが、
tool呼び出しの引数ストリーミング開始直後に生成を停止する不具合を実測で確認した
(settings.py::LLMSettings.openrouter_ignore_providers docstring参照)。
`openrouter_ignore_providers`が実際にモデルのdefault settingsへ反映されることを確認する。
"""

from __future__ import annotations

from polaris.agent.model import build_model
from polaris.settings import LLMSettings, Settings

_MODEL_ID = "qwen/qwen3.6-35b-a3b"


def test_build_model_ignores_configured_providers() -> None:
    """openrouter_ignore_providersがモデルのdefault settingsへそのまま反映される."""
    llm = LLMSettings(api_key="test-key", model_id=_MODEL_ID, openrouter_ignore_providers=["AkashML"])
    model = build_model(Settings(llm=llm))
    assert model.settings == {"openrouter_provider": {"ignore": ["AkashML"]}}


def test_build_model_omits_provider_setting_when_ignore_list_empty() -> None:
    """除外リストが空なら`openrouter_provider`キー自体を設定しない(余計なpayloadを送らない)."""
    llm = LLMSettings(api_key="test-key", model_id=_MODEL_ID, openrouter_ignore_providers=[])
    model = build_model(Settings(llm=llm))
    assert model.settings is None
