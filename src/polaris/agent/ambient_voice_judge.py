"""常時音声認識の判定+反応生成エージェント(026-voice-input Stage2代替案).

クライアントが`max_wait_seconds`ごとにフラッシュした文字起こしチャンクを渡し、
(a) 調べる/コメントする価値があるか、(b) あるなら`web_search`等の既存toolで調べた
上で一言コメントを生成する、を1回のエージェント実行で行う。`agent/paper_triage.py`と
同型(軽量モデル、reasoning無効)だが、tool呼び出しが要る点が異なる: `web_search.register`
(deps_type/output_typeを問わず任意のAgentに登録できる設計)をそのまま再利用して
`web_search`ツールを持たせる。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model
from .tools import web_search

if TYPE_CHECKING:
    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたは常時マイクで拾った独り言の書き起こしを見て、調べたり一言コメントしたりする
価値があるかを判定するアシスタントです。以下のルールに従ってください。

- 雑談・作業のつぶやき・意味の取れない断片など、反応する必要が無いものが大半です。
  迷ったら worth_reacting=false にしてください(誤反応の方が害が大きい)
- 明確な疑問・調べ物の要望・関連情報があれば役立ちそうな発言のときだけ
  worth_reacting=true にし、必要なら web_search ツールで調べた上で、
  日本語で1〜2文程度の簡潔なコメントを comment に書いてください
- 「前回チャンクの状況」が渡されていれば、話題が続いているかの参考にしてください
  (前回と同じ話題の続きなら、前回と重複しない新しい情報に絞ってコメントすること)
- worth_reacting=false のときは comment を空にしてください"""

_JUDGE_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class AmbientVoiceJudgment(BaseModel):
    """1チャンクぶんの判定結果."""

    worth_reacting: bool
    comment: str = ""


class AmbientVoiceJudge(Protocol):
    """AmbientVoiceJudgment を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def judge(self, *, transcript: str, previous_comment: str | None) -> AmbientVoiceJudgment:
        """書き起こしチャンク(+前回のコメント、あれば)から判定結果を作る."""
        ...


def build_ambient_voice_judge_agent(settings: Settings) -> Agent[None, AmbientVoiceJudgment]:
    """設定値から判定用のエージェントを組み立てる(軽量モデル、reasoningは無効化).

    `settings.ambient_voice.judge_model_id`(既定はQwen3-8B、`paper_research.triage_model_id`と
    同じ判断)を使う。`web_search.register`をそのまま呼び、既存のTavily連携ツールを
    持たせる(新規のtool実装は不要)。
    """
    agent = Agent(
        build_model(settings, model_id=settings.ambient_voice.judge_model_id),
        output_type=AmbientVoiceJudgment,
        instructions=_INSTRUCTIONS,
        model_settings=_JUDGE_MODEL_SETTINGS,
    )
    web_search.register(agent, settings=settings)
    return agent


class AgentAmbientVoiceJudge:
    """pydantic-ai エージェントをラップした AmbientVoiceJudge 実装."""

    def __init__(self, agent: Agent[None, AmbientVoiceJudgment]) -> None:
        """構造化出力エージェントを受け取って初期化する."""
        self._agent = agent

    async def judge(self, *, transcript: str, previous_comment: str | None) -> AmbientVoiceJudgment:
        """書き起こしチャンクをプロンプトにまとめてエージェントを実行する."""
        prompt = f"今回のチャンクの書き起こし:\n{transcript}"
        if previous_comment is not None:
            prompt += f"\n\n前回チャンクの状況(コメント済み): {previous_comment}"
        result = await self._agent.run(prompt)
        return result.output
