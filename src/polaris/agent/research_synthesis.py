"""関連論文調査の統合エージェント(027-related-paper-research 統合段).

**改訂(2026-09-13、`specs/027-related-paper-research/spec.draft.md`「改善: 統合結果が
薄い問題」参照)**: 当初は精読結果(課題/解決)を1論文ずつ`fold()`で順番に読み、
「前回までの統合結果(圧縮済み)」+「今回の1論文」だけを見せる**refine方式**だったが、
`max_deep_read`本(既定10本程度)を折り畳むと序盤の論文の情報が何重にも圧縮されて
実質失われ、統合結果が薄くなる不具合が実運用で見つかった。

各論文の課題/解決は短文(2〜3文)で、10本分を合計しても数百〜千数百語程度にしか
ならず、017の`rewrite()`と同じ「stuff」方式(全件を1回のプロンプトに収める)でも
十分コンテキストに収まる規模だった。refineで狙った省コンテキスト化のメリットが
この規模では効いていなかったため、**アウトライン先行方式**(AutoSurvey型)の
2段階に作り直す:

- **Step A(アウトライン生成)**: 全論文のタイトル+課題のみを渡し、レポートの
  見出し構成(いくつのサブテーマに分かれるか)を決めさせる軽量な呼び出し
- **Step B(本文生成)**: Step Aのアウトライン+全論文(タイトル・課題・解決すべて)を
  1回のプロンプトにまとめて渡し(stuff方式)、セクションごとに埋めさせる

この規模ではセクションごとに個別のLLM呼び出しを分ける本格的なAutoSurveyまでは
不要と判断した。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from collections.abc import Sequence

    from polaris.settings import Settings

_OUTLINE_INSTRUCTIONS = """\
あなたは、ある論文(起点論文)に関連する複数の論文を精読した結果から、調査レポートの
構成(アウトライン)を考えるアシスタントです。

- 渡されるのは各論文のタイトルと課題(この論文が取り組む問題)のみです
- 課題の傾向を見て、いくつのサブテーマに分かれるか、どんな見出しにするかを決めてください
  (無理に多く分けず、内容が近い論文はまとめてよい)
- 出力は見出しの箇条書きのみ(本文は書かない)。各見出しに、対応する論文のタイトルを
  括弧書きで添えてください"""

_SYNTHESIS_INSTRUCTIONS = """\
あなたは、ある論文(起点論文)に関連する複数の論文を精読した結果を、1つの調査レポートに
まとめるアシスタントです。

- 渡されるアウトライン(見出し構成)に沿って、各セクションの本文を書いてください
- 各論文のタイトル・課題・解決が渡されます。**どの論文の内容も漏らさず**本文に反映して
  ください(圧縮のしすぎで個々の論文の情報が失われないようにする)
- 「簡潔に」というのは冗長な前置き・結びの言葉を避ける、という意味であり、内容を
  削ってよいという意味ではありません
- 文章の最後に「参考論文」として、扱った論文のタイトルを列挙してください"""

_OUTLINE_MODEL_SETTINGS = OpenRouterModelSettings(
    max_tokens=2000,
    openrouter_reasoning={"enabled": False},
)

_SYNTHESIS_MODEL_SETTINGS = OpenRouterModelSettings(
    max_tokens=8000,
    openrouter_reasoning={"enabled": False},
)


class ResearchSynthesizer(Protocol):
    """統合結果(課題/解決の文章)を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def outline(self, *, seed_title: str, outcomes: Sequence[tuple[str, str]]) -> str:
        """全論文のタイトル+課題から、レポートの見出し構成(アウトライン)を決める(Step A)."""
        ...

    async def synthesize(self, *, seed_title: str, outline: str, outcomes: Sequence[tuple[str, str, str]]) -> str:
        """アウトライン+全論文(タイトル・課題・解決)から、レポート本文を1回で生成する(Step B)."""
        ...


def build_research_outline_agent(settings: Settings) -> Agent[None, str]:
    """設定値からアウトライン生成用(Step A)のエージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=str,
        instructions=_OUTLINE_INSTRUCTIONS,
        model_settings=_OUTLINE_MODEL_SETTINGS,
    )


def build_research_synthesis_agent(settings: Settings) -> Agent[None, str]:
    """設定値から本文生成用(Step B)のエージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=str,
        instructions=_SYNTHESIS_INSTRUCTIONS,
        model_settings=_SYNTHESIS_MODEL_SETTINGS,
    )


def _format_titles_and_problems(outcomes: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"- {title}\n  課題: {problem}" for title, problem in outcomes)


def _format_full_outcomes(outcomes: Sequence[tuple[str, str, str]]) -> str:
    return "\n\n".join(
        f"### {title}\n課題: {problem}\n解決: {solution}" for title, problem, solution in outcomes
    )


class AgentResearchSynthesizer:
    """pydantic-ai エージェントをラップした ResearchSynthesizer 実装(Step A/B で別々のエージェントを使う)."""

    def __init__(self, outline_agent: Agent[None, str], synthesis_agent: Agent[None, str]) -> None:
        """アウトライン生成・本文生成それぞれのエージェントを受け取って初期化する."""
        self._outline_agent = outline_agent
        self._synthesis_agent = synthesis_agent

    async def outline(self, *, seed_title: str, outcomes: Sequence[tuple[str, str]]) -> str:
        """起点論文名+全論文のタイトル・課題をプロンプトにまとめてStep Aを実行する."""
        prompt = f"起点論文: {seed_title}\n\n精読した論文一覧:\n{_format_titles_and_problems(outcomes)}"
        result = await self._outline_agent.run(prompt)
        return result.output

    async def synthesize(self, *, seed_title: str, outline: str, outcomes: Sequence[tuple[str, str, str]]) -> str:
        """起点論文名・アウトライン・全論文の精読結果をプロンプトにまとめてStep Bを実行する."""
        prompt = (
            f"起点論文: {seed_title}\n\n"
            f"アウトライン:\n{outline}\n\n"
            f"精読した論文一覧:\n{_format_full_outcomes(outcomes)}"
        )
        result = await self._synthesis_agent.run(prompt)
        return result.output
