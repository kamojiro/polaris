"""日記モード中の発話から過去日を推定する(019-diary-domain User Story 4).

日記の記録処理自体はtool呼び出しではなく`api/app.py`の後処理段のバックグラウンド処理
(`services/diary.py::record_diary_turn`)であるため、日付推定もメインのチャットエージェントの
外側で行う(`agent/extract_metadata.py`と同じ構造化抽出パターン、reasoningは無効化)。
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 - DateInferenceResultのフィールド型としてランタイムに解決される必要がある
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたは、日記モード中の会話が今日の出来事について話しているのか、過去の特定の日について
話しているのかを判定するアシスタントです。

- プロンプトには「今日の日付」が渡されます。会話の内容がその日について話している(または
  日付に言及していない)場合、target_dateはnullにしてください
- 「先週の水曜日」「8/25」「一昨日」のように過去の特定の日を明確に示唆している場合のみ、
  今日の日付を基準に実際の日付を計算してtarget_dateに入れてください
- 曖昧で日付を一意に特定できない場合はnullにしてください(推測で埋めない)
"""

_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class DateInferenceResult(BaseModel):
    """日付推定ステップの出力."""

    target_date: date | None = None


class DiaryDateInferrer(Protocol):
    """DateInferenceResult を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def infer(self, *, user_text: str, assistant_text: str, today: date) -> DateInferenceResult:
        """直近のやり取りと今日の日付から、対象とすべき過去日を推定する."""
        ...


def build_diary_date_infer_agent(settings: Settings) -> Agent[None, DateInferenceResult]:
    """設定値から日付推定用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=DateInferenceResult,
        instructions=_INSTRUCTIONS,
        model_settings=_MODEL_SETTINGS,
    )


class AgentDiaryDateInferrer:
    """pydantic-ai エージェントをラップした DiaryDateInferrer 実装."""

    def __init__(self, agent: Agent[None, DateInferenceResult]) -> None:
        """日付推定エージェントを受け取って初期化する."""
        self._agent = agent

    async def infer(self, *, user_text: str, assistant_text: str, today: date) -> DateInferenceResult:
        """直近のやり取りと今日の日付をプロンプトにまとめてエージェントを実行する."""
        prompt = f"今日の日付: {today}\n\nユーザー: {user_text}\nアシスタント: {assistant_text}"
        result = await self._agent.run(prompt)
        return result.output
