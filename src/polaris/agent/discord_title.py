"""Discordメッセージから表示用の短い見出し(display_title)を生成するエージェント(021-discord-integration).

`agent/sidebar_title.py`と同じ出力型(`SidebarTitle`)を再利用するが、あちらと違い
テキストを渡すだけの狭いタスクではない。Discordメッセージはurl単体・テキストのみ・
url+テキストの組み合わせ、いずれもありうる(2026-09-02、ユーザー確認)。

- urlが含まれる場合: スラッグだけから見出しを推測すると実際の内容と無関係な当て推量に
  なりやすい(実機確認: あるブログの記事URLが、実際の記事内容とは無関係などール
  キャラクターについての見出しに誤って推測された)ため、`chat_agent.py`と同じ`web_fetch`
  ツール(pydantic-ai同梱)を登録し、実際のページを読んでから見出しを作らせる
- urlを含まない単語・短い語句だけのメッセージの場合: 本文だけでは何を指しているか
  分からないことがある(2026-09-02、ユーザー確認)ため、`agent/tools/web_search.py`の
  `web_search`ツール(自前ホストのSearXNG)も同様に登録し、必要なら調べさせる

「fetch/searchするか・その結果をどう見出しに落とすか」自体がタスクの一部なので、
正規表現でのurl抽出+手動ツール呼び出しではなくエージェントに判断させる。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic_ai import Agent
from pydantic_ai.common_tools.web_fetch import web_fetch_tool
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model
from .sidebar_title import SidebarTitle
from .tools import web_search

if TYPE_CHECKING:
    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたはDiscordのあるチャンネルに投稿されたメッセージ1件から、サイドバー表示用の
短い日本語見出しを作るアシスタントです。メッセージはURLのみ・テキストのみ・
URLとテキストの組み合わせ、いずれの形もありえます。

- メッセージにURLが含まれる場合、web_fetchツールでそのURLの内容を実際に確認してから
  見出しを作ってください。URLのスラッグや見た目だけから内容を推測してはいけません
- web_fetchが失敗した場合(存在しないページ、アクセス不可等)は、メッセージ本文だけを
  手がかりに見出しを作ってください
- メッセージが単語や短い語句だけで、それが何を指しているか自明でない場合は、
  web_searchツールで調べてから見出しを作ってください。自明な内容(挨拶・一般的な言葉等)
  であれば無理に調べる必要はありません
- display_title: 20文字前後を目安にした、内容が一目でわかる日本語の見出し。
  「〜について」のような冗長な言い回しは避ける
"""

# web_fetchを呼ぶかどうか・その結果をどう見出しに落とすかという判断が要るタスクのため、
# sidebar_title.pyと違いreasoningは無効化しない。
#
# 実装時の訂正(2026-09-02): 当初max_tokens=3000/reasoning.max_tokens=1000で運用したが、
# web_fetch/web_searchでページ内容を読んでから判断させる実機テストで
# "Model token limit (3000) exceeded before any response was generated"/
# "Exceeded maximum output retries"に複数件遭遇した。chat_agent.py(2026-08-31実装時訂正)と
# 同じ原因(`openrouter_reasoning.max_tokens`はOpenRouter経由のオープンウェイトモデルに
# 対してはソフトな目安に留まり、ページ内容を踏まえた判断でreasoningだけで上限近くまで
# 使うことがある)のため、同じ値をそのまま踏襲する。
_DISCORD_TITLE_MODEL_SETTINGS = OpenRouterModelSettings(
    max_tokens=32000,
    openrouter_reasoning={"max_tokens": 4000},
)

# web_fetchが返すページ内容(markdown化後)の最大文字数。見出し生成にはタイトル程度で
# 十分なため、chat_agent.py の既定(50,000文字)よりずっと小さく絞る。
_FETCH_MAX_CONTENT_LENGTH = 3000


class DiscordTitler(Protocol):
    """SidebarTitle を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def title(self, content: str) -> SidebarTitle:
        """Discordメッセージ本文から表示用の短い見出しを生成する."""
        ...


def build_discord_title_agent(settings: Settings) -> Agent[None, SidebarTitle]:
    """設定値からDiscord見出し生成用の pydantic-ai エージェントを組み立てる(web_fetch/web_search登録済み)."""
    agent = Agent(
        build_model(settings),
        output_type=SidebarTitle,
        instructions=_INSTRUCTIONS,
        # 見出し生成には本文全体は不要(タイトルが分かれば十分)。chat_agent.py の
        # web_fetch(既定50,000文字)をそのまま登録すると、長い記事1件でreasoningの
        # トークン予算を使い切ってしまうことを実機確認したため、大きく絞る。
        tools=[web_fetch_tool(max_content_length=_FETCH_MAX_CONTENT_LENGTH)],
        model_settings=_DISCORD_TITLE_MODEL_SETTINGS,
    )
    web_search.register(agent, settings=settings)
    return agent


class AgentDiscordTitler:
    """pydantic-ai エージェントをラップした DiscordTitler 実装."""

    def __init__(self, agent: Agent[None, SidebarTitle]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def title(self, content: str) -> SidebarTitle:
        """メッセージ本文をそのままエージェントに渡して実行する."""
        result = await self._agent.run(content)
        return result.output
