"""1日分の活動を横断要約するエージェント(023-daily-summary-notification).

`structure_news.py`と同じ「Protocol + Agentラッパー」の形を踏襲するが、2点違う。

- 出力は構造化オブジェクトではなく自然な文章(`Agent[None, str]`)。決まったスキーマを
  埋めるタスクではなく、複数ドメインを横断して「今日は何をした日か」をまとめる作業のため
- reasoningは無効化しない(他のStructure系エージェントと違い、狭いタスクではないため
  モデルの既定に任せる)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic_ai import Agent

from .model import build_model

if TYPE_CHECKING:
    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたはPolaris(個人用ナレッジ管理ツール)の1日分の活動ログから、日次サマリーを書くアシスタントです。

- 与えられた活動(論文の保存、TODOの追加・完了、記憶の更新、読んだニュース記事)を
  日本語で自然な文章にまとめる。箇条書きの単純な転記ではなく、その日何をしたかが
  一目で分かるような、短い(3〜5文程度の)まとめにする
- 与えられていない情報を推測して補わない
"""


class DailySummarizer(Protocol):
    """活動ログのプロンプトから要約文を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def summarize(self, activity_prompt: str) -> str:
        """1日分の活動をまとめたプロンプトから、要約文を生成する."""
        ...


def build_daily_summary_agent(settings: Settings) -> Agent[None, str]:
    """設定値から日次サマリー用の pydantic-ai エージェントを組み立てる.

    メインのチャットモデル(`settings.llm.model_id`)を使う。複数ドメインを横断して
    自然な文章にまとめる必要があり、017の想起用軽量モデル(qwen3-8b)より能力が要ると
    判断したため(2026-08-30)。
    """
    return Agent(build_model(settings), output_type=str, instructions=_INSTRUCTIONS)


class AgentDailySummarizer:
    """pydantic-ai エージェントをラップした DailySummarizer 実装."""

    def __init__(self, agent: Agent[None, str]) -> None:
        """要約エージェントを受け取って初期化する."""
        self._agent = agent

    async def summarize(self, activity_prompt: str) -> str:
        """活動ログのプロンプトをそのままエージェントに渡して実行する."""
        result = await self._agent.run(activity_prompt)
        return result.output
