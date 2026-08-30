"""日記ドメイン(019-diary-domain)の現在状態層の書き直し(後処理段).

`agent/memory_extract.py`のrewrite半分と同型。「記憶に値するか」の判定ステップ
(017の`MemoryExtractor`相当)は無い — 日記モード中の会話は無条件に記録対象のため
(research.md Decision 3)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from collections.abc import Sequence

    from polaris.settings import Settings

_REWRITE_INSTRUCTIONS = """\
あなたは、ある1日の会話の断片(時系列順)から、その日の日記を1つの自然な文章として
まとめるアシスタントです。

- 出力は日記本文のみ(見出し等は不要)
- 断片を単純に列挙するのではなく、その日にあったことを一人称の日記らしい自然な文章に
  まとめてください
- 簡潔に。冗長な前置きや結びの言葉は不要です
"""

_DIARY_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class DiaryRewriter(Protocol):
    """その日の日記本文を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def rewrite(self, *, raw_texts: Sequence[str]) -> str:
        """時系列の会話断片から、その日の日記本文を合成する."""
        ...


def build_diary_rewrite_agent(settings: Settings) -> Agent[None, str]:
    """設定値から日記の書き直し用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=str,
        instructions=_REWRITE_INSTRUCTIONS,
        model_settings=_DIARY_MODEL_SETTINGS,
    )


class AgentDiaryRewriter:
    """pydantic-ai エージェントをラップした DiaryRewriter 実装."""

    def __init__(self, agent: Agent[None, str]) -> None:
        """書き直しエージェントを受け取って初期化する."""
        self._agent = agent

    async def rewrite(self, *, raw_texts: Sequence[str]) -> str:
        """時系列の会話断片をプロンプトにまとめてエージェントを実行する."""
        history = "\n".join(f"- {text}" for text in raw_texts)
        result = await self._agent.run(f"今日の会話の断片(時系列):\n{history}")
        return result.output
