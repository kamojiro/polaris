"""記憶テーマの定期棚卸し(024-memory-theme-housekeeping)の検出エージェント.

`agent/memory_extract.py`と同じ「Protocol + Agentラッパー」の形を踏襲する。全テーマの現在状態
ファイルを1回のLLM呼び出しでまとめて評価する(research.md Decision 3: テーマ間の重複・分割は
複数テーマを横断した判断が要るため、テーマごとの個別呼び出しにはしない)。

`023-daily-summary-notification`の日次サマリーエージェントと同じくreasoningは無効化しない
(狭いスキーマ埋めではなく、複数テーマを横断した判断が要るため。research.md Decision 4)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent

from .model import build_model

if TYPE_CHECKING:
    from collections.abc import Sequence

    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたはPolaris(個人用ナレッジ管理ツール)のチャット長期記憶(記憶テーマ)を棚卸しする
アシスタントです。各テーマは slug・現在の内容(Markdown)・最終更新日時を持ちます。

以下の3種類の整理候補を検出してください(該当が無ければ何も出力しなくてよい)。

- merge(統合): 複数のテーマの内容が明らかに重複している
- split(分割): 1つのテーマに複数の異なる話題が混在している
- stale(長期未更新): 長期間更新されておらず、実質的に使われなくなっていると判断できる

各候補には、対象テーマのslug(複数可)と、なぜその候補だと判断したかの具体的な理由を
日本語で簡潔に記述してください。確信が持てない候補は無理に挙げず、明確な根拠があるものだけを
報告してください。
"""


class HousekeepingSuggestionItem(BaseModel):
    """検出された整理候補1件."""

    suggestion_type: Literal["merge", "split", "stale"]
    target_theme_slugs: list[str]
    detail: str


class HousekeepingDetectionResult(BaseModel):
    """検出処理1回分の結果(0件もありうる)."""

    suggestions: list[HousekeepingSuggestionItem]


class MemoryHousekeepingDetector(Protocol):
    """HousekeepingDetectionResult を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def detect(self, *, themes: Sequence[tuple[str, str, str]]) -> HousekeepingDetectionResult:
        """全テーマ(slug, 現在状態ファイル全文, 最終更新日時のISO文字列)を渡し、整理候補を検出する."""
        ...


def build_memory_housekeeping_agent(settings: Settings) -> Agent[None, HousekeepingDetectionResult]:
    """設定値から検出用の pydantic-ai エージェントを組み立てる.

    メインのチャットモデル(`settings.llm.model_id`)を使う。複数テーマを横断して重複・分割を
    判断する必要があり、017の想起用軽量モデルより能力が要ると判断したため(research.md Decision 4)。
    """
    return Agent(build_model(settings), output_type=HousekeepingDetectionResult, instructions=_INSTRUCTIONS)


class AgentMemoryHousekeepingDetector:
    """pydantic-ai エージェントをラップした MemoryHousekeepingDetector 実装."""

    def __init__(self, agent: Agent[None, HousekeepingDetectionResult]) -> None:
        """検出エージェントを受け取って初期化する."""
        self._agent = agent

    async def detect(self, *, themes: Sequence[tuple[str, str, str]]) -> HousekeepingDetectionResult:
        """テーマ一覧をプロンプトに整形してエージェントに渡す."""
        if not themes:
            return HousekeepingDetectionResult(suggestions=[])

        lines = [
            f"## テーマ: {slug}(最終更新: {updated_at})\n{content}" for slug, content, updated_at in themes
        ]
        result = await self._agent.run("\n\n---\n\n".join(lines))
        return result.output
