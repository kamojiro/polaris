"""欠落メタデータ・summary を生成する構造化出力エージェント.

spec の処理フロー 5番目のステップ(「Structure: Pydantic AI エージェントで
欠落メタデータ・要約を生成」)に対応する。スキーマ検証に失敗した場合は
pydantic-ai の通常の retries に従う(追加のフォールバックは実装しない)。
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
あなたは学術論文のメタデータを整理するアシスタントです。
タイトル・abstract・コメント欄(あれば)から次を生成してください。

- summary: 日本語で3〜5文程度の簡潔な要約
- venue: 掲載先の会議・ジャーナル名がコメント欄等から明確に読み取れる場合のみ記入し、
  分からなければ null にする(推測で埋めない)
"""


# summary/venue の構造化出力が安定して返れば十分で、reasoning(思考過程)は不要な上に
# レイテンシとコストが増えるだけなので明示的に無効化する。openrouter_reasoning だけでは
# ルーティング先のプロバイダによっては無視されることがあるため、Qwen3系の
# chat_template_kwargs.enable_thinking も併せて渡しておく(二重の抑制)。
_STRUCTURE_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class StructuredPaper(BaseModel):
    """Structure ステップの出力."""

    summary: str
    venue: str | None


class PaperStructurer(Protocol):
    """StructuredPaper を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def structure(self, *, title: str, abstract: str, comment: str | None) -> StructuredPaper:
        """タイトル・abstract・コメントから summary/venue を生成する."""
        ...


def build_structure_agent(settings: Settings) -> Agent[None, StructuredPaper]:
    """設定値から Structure 用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=StructuredPaper,
        instructions=_INSTRUCTIONS,
        model_settings=_STRUCTURE_MODEL_SETTINGS,
    )


class AgentPaperStructurer:
    """pydantic-ai エージェントをラップした PaperStructurer 実装."""

    def __init__(self, agent: Agent[None, StructuredPaper]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def structure(self, *, title: str, abstract: str, comment: str | None) -> StructuredPaper:
        """タイトル・abstract・コメントをプロンプトにまとめてエージェントを実行する."""
        prompt = f"タイトル: {title}\nAbstract: {abstract}\nコメント: {comment or 'なし'}"
        result = await self._agent.run(prompt)
        return result.output
