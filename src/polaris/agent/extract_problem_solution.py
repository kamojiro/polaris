"""関連論文調査の精読エージェント(027-related-paper-research 精読段).

`extract_metadata.py`/`structure_paper.py`の要約とは別軸の抽出。論文の全文
(`services/paper_full_text.load_full_text`で取得)から「課題(この論文が取り組む
未解決の問題)」「解決(この論文が示した解決・知見)」の2軸を抽出する。結果は
`PaperDeepAnalysisRecord`としてitem_id単位でキャッシュされ、他の調査から再利用される
(`db/paper_research_repository.py::PaperDeepAnalysisRepository`)。
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
あなたは学術論文を精読し、その論文が研究上どこに位置づけられるかを整理する
アシスタントです。タイトルと本文全文から、次の2つを日本語で抽出してください。

- problem: この論文が取り組んでいる未解決の課題・問題設定(2〜3文程度)
- solution: この論文が示した解決策・知見(2〜3文程度、具体的な手法名を含めてよい)

本文が長い場合でも、要点を過不足なく抽出してください。推測で内容を補わず、
本文に書かれている範囲で答えてください。"""

# 構造化出力(problem/solution)が安定して返れば十分で、reasoningは不要な上に
# 長い全文を読ませるタスクでレイテンシ・コストが余計に増えるため明示的に無効化する
# (structure_paper.pyと同じ判断)。
_EXTRACT_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class ProblemSolution(BaseModel):
    """精読ステップの出力."""

    problem: str
    solution: str


class PaperProblemSolutionExtractor(Protocol):
    """ProblemSolution を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def extract(self, *, title: str, body_text: str) -> ProblemSolution:
        """論文のタイトル・本文全文から課題/解決を抽出する."""
        ...


def build_extract_problem_solution_agent(settings: Settings) -> Agent[None, ProblemSolution]:
    """設定値から精読用のエージェントを組み立てる(メインモデル、reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=ProblemSolution,
        instructions=_INSTRUCTIONS,
        model_settings=_EXTRACT_MODEL_SETTINGS,
    )


class AgentPaperProblemSolutionExtractor:
    """pydantic-ai エージェントをラップした PaperProblemSolutionExtractor 実装."""

    def __init__(self, agent: Agent[None, ProblemSolution]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def extract(self, *, title: str, body_text: str) -> ProblemSolution:
        """タイトル・本文全文をプロンプトにまとめてエージェントを実行する."""
        prompt = f"タイトル: {title}\n\n本文:\n{body_text}"
        result = await self._agent.run(prompt)
        return result.output
