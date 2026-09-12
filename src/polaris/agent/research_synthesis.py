"""関連論文調査の統合エージェント(027-related-paper-research 統合段).

精読結果(課題/解決)を1論文ずつ順番に見ていき、「テーマの課題」「解決済みのこと」を
逐次合成する。`agent/diary_rewrite.py`/`agent/memory_extract.py`の書き直しと違い、
毎回すべての生テキストを渡し直す「stuff」方式ではなく、前回までの統合結果(previous)
に新しい1論文の精読結果を織り込む「refine」方式(`specs/IDEAS.md`の整理参照)。調査
1件で最大`paper_research.max_deep_read`本を1本ずつ処理するため、毎回全件を渡すより
プロンプトが安定して短く保てる。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from polaris.settings import Settings

_SYNTHESIS_INSTRUCTIONS = """\
あなたは、ある論文(起点論文)に関連する論文を1本ずつ精読した結果から、テーマ全体の
理解を1つの文章にまとめていくアシスタントです。

- 出力は「このテーマの課題」「これまでに分かっている解決・知見」を中心にした
  日本語の文章(見出しを使ってよい)
- これまでの統合結果(初回はまだ無い)に、新しく精読した1論文の課題/解決を織り込んで
  更新してください。単純な追記ではなく、重複や矛盾があれば整理し、テーマ全体として
  一貫した理解になるようにしてください
- 文章の最後に「参考論文」として、これまでに織り込んだ論文のタイトルを列挙してください
- 簡潔に。冗長な前置きは不要です"""

_SYNTHESIS_MODEL_SETTINGS = OpenRouterModelSettings(
    max_tokens=8000,
    openrouter_reasoning={"enabled": False},
)


class ResearchSynthesizer(Protocol):
    """統合結果(課題/解決の文章)を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def fold(
        self, *, seed_title: str, previous: str | None, paper_title: str, problem: str, solution: str
    ) -> str:
        """前回までの統合結果に、新しく精読した1論文の課題/解決を織り込む."""
        ...


def build_research_synthesis_agent(settings: Settings) -> Agent[None, str]:
    """設定値から統合用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=str,
        instructions=_SYNTHESIS_INSTRUCTIONS,
        model_settings=_SYNTHESIS_MODEL_SETTINGS,
    )


class AgentResearchSynthesizer:
    """pydantic-ai エージェントをラップした ResearchSynthesizer 実装."""

    def __init__(self, agent: Agent[None, str]) -> None:
        """書き直しエージェントを受け取って初期化する."""
        self._agent = agent

    async def fold(
        self, *, seed_title: str, previous: str | None, paper_title: str, problem: str, solution: str
    ) -> str:
        """起点論文名・前回までの統合結果・新規論文の精読結果をプロンプトにまとめて実行する."""
        previous_block = previous if previous is not None else "(まだありません、これが1本目です)"
        prompt = (
            f"起点論文: {seed_title}\n\n"
            f"これまでの統合結果:\n{previous_block}\n\n"
            f"新しく精読した論文:\nタイトル: {paper_title}\n課題: {problem}\n解決: {solution}"
        )
        result = await self._agent.run(prompt)
        return result.output
