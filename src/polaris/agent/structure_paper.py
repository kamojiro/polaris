"""欠落メタデータ・summary を生成する構造化出力エージェント.

spec の処理フロー 5番目のステップ(「Structure: Pydantic AI エージェントで
欠落メタデータ・要約を生成」)に対応する。スキーマ検証に失敗した場合は
pydantic-ai の通常の retries に従う(追加のフォールバックは実装しない)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent

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
    """設定値から Structure 用の pydantic-ai エージェントを組み立てる."""
    return Agent(build_model(settings), output_type=StructuredPaper, instructions=_INSTRUCTIONS)


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
