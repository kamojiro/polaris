"""ニュース記事の短い要約を生成する構造化出力エージェント(008-daily-digest-domain Phase A).

`structure_paper.py`と同じ「狭いタスクを小さいモデルに閉じてやらせる」パターン。
記事単位のトピック分類はしない(source_labelはフィード単位で静的に決まるため、
spec の対立軸の定義方針に従い記事単位のLLM自動分類は行わない)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたはニュース記事・技術ブログ記事のタイトルと概要から、短い要約を作るアシスタントです。

- summary: 日本語で1〜2文程度の簡潔な要約。概要(HTMLタグを含むことがある)の内容を
  そのまま転記するのではなく、何についての記事かが一目で分かるように書く
"""

# structure_paper.py と同じ理由(構造化出力が安定して返れば十分で reasoning は不要)で
# 明示的に無効化する。
_STRUCTURE_NEWS_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class StructuredNews(BaseModel):
    """Structure ステップの出力."""

    summary: str


class NewsStructurer(Protocol):
    """StructuredNews を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def structure(self, *, title: str, summary: str) -> StructuredNews:
        """タイトル・概要から短い要約を生成する."""
        ...


def build_structure_news_agent(settings: Settings) -> Agent[None, StructuredNews]:
    """設定値からニュース要約用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=StructuredNews,
        instructions=_INSTRUCTIONS,
        model_settings=_STRUCTURE_NEWS_MODEL_SETTINGS,
    )


class AgentNewsStructurer:
    """pydantic-ai エージェントをラップした NewsStructurer 実装."""

    def __init__(self, agent: Agent[None, StructuredNews]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def structure(self, *, title: str, summary: str) -> StructuredNews:
        """タイトル・概要をプロンプトにまとめてエージェントを実行する."""
        prompt = f"タイトル: {title}\n概要: {summary or 'なし'}"
        result = await self._agent.run(prompt)
        return result.output
