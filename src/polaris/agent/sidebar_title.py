"""サイドバー表示用の短い見出しを生成する構造化出力エージェント(008-daily-digest-domain拡張).

`structure_news.py`と同じ「狭いタスクを小さいモデルに閉じてやらせる」パターン。
元のタイトル(英語のことが多い)+要約(arXivのtitle-onlyエントリでは無いこともある)
から、サイドバーの限られた幅で一目で内容がわかる短い日本語見出しを作る。
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
あなたはニュース記事・論文のタイトルと要約(無いこともある)から、サイドバー表示用の
短い日本語見出しを作るアシスタントです。

- display_title: 20文字前後を目安にした、内容が一目でわかる日本語の見出し。
  元のタイトルが英語でも日本語に訳してよい。「〜について」のような冗長な言い回しは避ける
"""

# structure_news.py と同じ理由(構造化出力が安定して返れば十分でreasoningは不要)で
# 明示的に無効化する。
_SIDEBAR_TITLE_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class SidebarTitle(BaseModel):
    """Sidebar見出し生成ステップの出力."""

    display_title: str


class SidebarTitler(Protocol):
    """SidebarTitle を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def title(self, *, title: str, summary: str) -> SidebarTitle:
        """タイトル・要約から短い表示用見出しを生成する."""
        ...


def build_sidebar_title_agent(settings: Settings) -> Agent[None, SidebarTitle]:
    """設定値からサイドバー見出し生成用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=SidebarTitle,
        instructions=_INSTRUCTIONS,
        model_settings=_SIDEBAR_TITLE_MODEL_SETTINGS,
    )


class AgentSidebarTitler:
    """pydantic-ai エージェントをラップした SidebarTitler 実装."""

    def __init__(self, agent: Agent[None, SidebarTitle]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def title(self, *, title: str, summary: str) -> SidebarTitle:
        """タイトル・要約をプロンプトにまとめてエージェントを実行する."""
        prompt = f"タイトル: {title}\n要約: {summary or 'なし'}"
        result = await self._agent.run(prompt)
        return result.output
