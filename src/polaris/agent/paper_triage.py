"""関連論文調査の粗い判定(triage)エージェント(027-related-paper-research 発見段の次段).

候補プールを`triage_batch_size`件ずつバッチにし、各論文のtitle/abstractを見せて
「起点論文のテーマに関連し、精読する価値があるか」を判定する。abstractは
**英語原文のまま**渡す(日本語訳はしない、spec方針: LLMの学習データは技術文書だと
英語が厚く、翻訳を挟むより原文を直接読ませた方が精度が高い。翻訳が要るのは
人間に見せる表示層のみ)。候補はプロンプト上で1..Nの連番にして番号で結果を
突き合わせる(不透明な`paperId`文字列はモデルが崩しやすいため)。
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
あなたは学術論文の関連性を判定するアシスタントです。起点論文のタイトル・abstractと、
番号付きの候補論文一覧(タイトル・abstract)が渡されます。各候補について、
起点論文のテーマに関連し、精読する価値があるかを判定してください。

- 単にキーワードが似ているだけでなく、起点論文の課題設定・手法・応用分野のいずれかと
  実質的に関連しているかで判断してください
- items には渡された候補と同じ数だけ、対応する番号(index)を含む判定結果を含めてください
- reason は日本語で1文程度、判定理由を簡潔に書いてください"""

_TRIAGE_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class TriageItem(BaseModel):
    """候補論文1件分の判定結果."""

    index: int
    relevant: bool
    reason: str


class TriageResult(BaseModel):
    """triageステップの出力(候補プール1バッチ分)."""

    items: list[TriageItem]


class PaperTriager(Protocol):
    """TriageResult を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def triage(
        self, *, seed_title: str, seed_abstract: str, candidates: Sequence[tuple[str, str]]
    ) -> TriageResult:
        """起点論文と候補論文一覧(title, abstract)から関連可否を判定する."""
        ...


def build_paper_triage_agent(settings: Settings) -> Agent[None, TriageResult]:
    """設定値からtriage用のエージェントを組み立てる(軽量モデル、reasoningは無効化).

    `settings.paper_research.triage_model_id`(既定はQwen3-8B)を使う。関連可否の
    二値判定+短い理由付けという単純な分類タスクのため、メインのチャットモデルより
    軽量なモデルで十分と判断した(`memory_recall.py`と同じ判断)。
    """
    return Agent(
        build_model(settings, model_id=settings.paper_research.triage_model_id),
        output_type=TriageResult,
        instructions=_INSTRUCTIONS,
        model_settings=_TRIAGE_MODEL_SETTINGS,
    )


def _format_candidates(candidates: Sequence[tuple[str, str]]) -> str:
    lines = [f"{i}. タイトル: {title}\n   Abstract: {abstract}" for i, (title, abstract) in enumerate(candidates, 1)]
    return "\n".join(lines)


class AgentPaperTriager:
    """pydantic-ai エージェントをラップした PaperTriager 実装."""

    def __init__(self, agent: Agent[None, TriageResult]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def triage(
        self, *, seed_title: str, seed_abstract: str, candidates: Sequence[tuple[str, str]]
    ) -> TriageResult:
        """起点論文と候補論文一覧をプロンプトにまとめてエージェントを実行する."""
        prompt = (
            f"起点論文:\nタイトル: {seed_title}\nAbstract: {seed_abstract}\n\n"
            f"候補論文一覧:\n{_format_candidates(candidates)}"
        )
        result = await self._agent.run(prompt)
        return result.output
