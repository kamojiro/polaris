"""関連論文調査の発見段(027-related-paper-research)で使うキーワード抽出エージェント.

引用チェイニング(backward/forward/2hop)だけでは見つからない関連論文を補うため、
起点論文のタイトル・abstractから軽量LLM呼び出しでキーワードを2〜3個抽出し、
Semantic Scholarのキーワード検索(`adapters/semantic_scholar/client.py::search_papers`)
に渡す。`memory_recall.py`と同じ「狭いタスクを軽いモデルに閉じてやらせる」パターン
(`settings.paper_research.triage_model_id`を再利用、粗い判定と同じ軽さで十分)。
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
論文のタイトルとabstractから、関連論文をSemantic Scholarで検索するための
キーワードを2〜3個抽出してください。論文の核心的な手法・問題設定を表す
具体的な語句を選び、一般的すぎる語(例:「deep learning」単体)は避けてください。"""

_KEYWORDS_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class ResearchKeywords(BaseModel):
    """キーワード抽出の出力."""

    keywords: list[str]


class ResearchKeywordExtractor(Protocol):
    """ResearchKeywords を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def extract(self, *, title: str, abstract: str) -> ResearchKeywords:
        """論文のタイトル・abstractからキーワードを抽出する."""
        ...


def build_research_keywords_agent(settings: Settings) -> Agent[None, ResearchKeywords]:
    """設定値からキーワード抽出用の軽量エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings, model_id=settings.paper_research.triage_model_id),
        output_type=ResearchKeywords,
        instructions=_INSTRUCTIONS,
        model_settings=_KEYWORDS_MODEL_SETTINGS,
    )


class AgentResearchKeywordExtractor:
    """pydantic-ai エージェントをラップした ResearchKeywordExtractor 実装."""

    def __init__(self, agent: Agent[None, ResearchKeywords]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def extract(self, *, title: str, abstract: str) -> ResearchKeywords:
        """タイトル・abstractをプロンプトにまとめてエージェントを実行する."""
        prompt = f"タイトル: {title}\n\nAbstract:\n{abstract}"
        result = await self._agent.run(prompt)
        return result.output
