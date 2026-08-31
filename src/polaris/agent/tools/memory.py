"""チャットの長期記憶の動的instructions注入(ADR-0013で chat_agent.py から分割).

017-chat-memory。メインのチャットエージェントに「記憶を検索するtool」を持たせない
(応答生成モデルに能動的なtool呼び出しを期待するのは信頼性が低いため)。代わりに
`api/app.py` の前処理段が想起した内容を `ChatDeps.recalled_memory` に詰めて渡し、
`_memory_instructions` がそれを動的instructionsとして注入する。抽出(後処理)は
完全にこのエージェントの外側(`services/memory.py`)で行われ、チャットの応答自体には
一切関与しない。tool は登録しない、静的なinstructions断片も無い(動的注入のみ)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# RunContext/ChatDeps は _memory_instructions の引数の型注釈として使われ、pydantic-ai が
# 実行時にシグネチャから解決する(`from __future__ import annotations` で文字列注釈に
# なるため、TYPE_CHECKING ブロックに入れると実行時に解決できず NameError になる)。
# そのため ruff の TC001/TC002 は意図的に無視する。
from pydantic_ai import RunContext  # noqa: TC002

from polaris.agent.chat_state import ChatDeps  # noqa: TC001

if TYPE_CHECKING:
    from pydantic_ai import Agent


def register(agent: Agent[ChatDeps, str]) -> None:
    """想起した長期記憶(017-chat-memory)を動的instructionsとして注入する."""

    @agent.instructions
    def _memory_instructions(ctx: RunContext[ChatDeps]) -> str | None:
        if ctx.deps.recalled_memory is None:
            return None
        return (
            "以下は過去の会話から蓄積した、関連するテーマについての記憶です。"
            "踏まえた上で回答してください。\n\n" + ctx.deps.recalled_memory
        )
