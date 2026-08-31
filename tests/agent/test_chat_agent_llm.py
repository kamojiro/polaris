"""chat_agentの完了トークン予算(`_CHAT_MODEL_SETTINGS`)の実LLM回帰テスト.

`llm`マーカー(既定では除外、`uv run nox -s test_llm`で明示実行、`pyproject.toml`参照)。

2026-08-31、`_CHAT_MODEL_SETTINGS`の`max_tokens`を8000に設定した際、「表形式で詳しく
比較して」のような正当に長い応答が必要な質問でも
"Model token limit exceeded before any response was generated"エラーで応答生成自体が
失敗する不具合が実機で発生した(`specs/019-diary-domain/research.md` Decision 11の
「実装時の訂正」参照)。原因は`openrouter_reasoning.max_tokens`がAnthropicの
`budget_tokens`のような厳密なハード上限ではなく、OpenRouter経由のオープンウェイト
モデルに対してはソフトな目安に留まること(reasoningだけで設定値を超えて消費しうる)。
フェイクでは再現できない、実際のreasoning/出力トークン消費量に依存する不具合のため、
実LLM呼び出しでこの種の質問が完了することを確認する。
"""

from __future__ import annotations

import pytest
from pydantic_ai import Agent

from polaris.agent.chat_agent import _CHAT_MODEL_SETTINGS, _INSTRUCTIONS
from polaris.agent.model import build_model
from polaris.settings import Settings

pytestmark = pytest.mark.llm

_LONG_ANSWER_PROMPT = (
    "大阪でつけ麺食べたいんだけど、有名店を5つくらい挙げて、それぞれの特徴と選び方の"
    "ポイントを詳しく表形式で整理して説明して"
)
# 空応答や極端な短文(エラーメッセージ相当)ではないことだけを確認する最低限のしきい値。
_MIN_OUTPUT_CHARS = 200


async def test_chat_model_settings_allow_long_structured_answer() -> None:
    """`_CHAT_MODEL_SETTINGS`の完了トークン上限が、正当に長い応答を妨げないことを確認する."""
    settings = Settings()
    agent = Agent(build_model(settings), instructions=_INSTRUCTIONS, model_settings=_CHAT_MODEL_SETTINGS)

    result = await agent.run(_LONG_ANSWER_PROMPT)

    assert len(result.output) > _MIN_OUTPUT_CHARS
