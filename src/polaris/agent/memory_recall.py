"""チャット長期記憶(017-chat-memory)の想起(前処理段).

`/api/chat`のメインのチャットエージェント呼び出しの前に、直近のユーザー発言と
テーマ索引(slug + 一行説明)を渡し、該当するテーマがあるかを判定させる専用の
軽量エージェント。メインのチャットエージェントに「記憶を検索するtool」は持たせない
(spec: 応答生成モデルに能動的なtool呼び出しを期待するのは信頼性が低いため)。
`structure_paper.py`/`extract_metadata.py`と同じ「狭いタスクを小さいモデルに
閉じてやらせる」パターン。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from collections.abc import Sequence

    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたはチャットの長期記憶システムの一部として、直近のユーザー発言が既存のどの
テーマに関連するかを判定するアシスタントです。

- テーマ一覧(slug + 一行説明)とユーザー発言が渡されます
- 発言の内容が既存テーマのいずれかに関連していれば、該当する slug を挙げてください
  (複数のテーマに関連していれば複数挙げてよい)
- どのテーマにも関連しない、または単なる挨拶・雑談であれば matched_theme_slugs は
  空リストにしてください。無理に関連付けない(false positiveの方が実害が大きい)
"""

_RECALL_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class RecallResult(BaseModel):
    """想起ステップの出力."""

    matched_theme_slugs: list[str]


class MemoryRecaller(Protocol):
    """RecallResult を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def recall(self, *, recent_text: str, themes: Sequence[tuple[str, str]]) -> RecallResult:
        """直近の発言とテーマ一覧から、該当するテーマのslugを判定する."""
        ...


def build_memory_recall_agent(settings: Settings) -> Agent[None, RecallResult]:
    """設定値から想起用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=RecallResult,
        instructions=_INSTRUCTIONS,
        model_settings=_RECALL_MODEL_SETTINGS,
    )


def _format_themes(themes: Sequence[tuple[str, str]]) -> str:
    if not themes:
        return "(テーマなし)"
    return "\n".join(f"- {slug}: {description}" for slug, description in themes)


class AgentMemoryRecaller:
    """pydantic-ai エージェントをラップした MemoryRecaller 実装."""

    def __init__(self, agent: Agent[None, RecallResult]) -> None:
        """想起エージェントを受け取って初期化する."""
        self._agent = agent

    async def recall(self, *, recent_text: str, themes: Sequence[tuple[str, str]]) -> RecallResult:
        """直近の発言とテーマ一覧をプロンプトにまとめてエージェントを実行する."""
        prompt = f"テーマ一覧:\n{_format_themes(themes)}\n\nユーザー発言:\n{recent_text}"
        result = await self._agent.run(prompt)
        return result.output
