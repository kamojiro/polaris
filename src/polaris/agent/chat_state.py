"""メインのチャットエージェントの deps/state 定義(ADR-0013).

`agent/tools/*.py`(ドメインごとのtool登録)は`RunContext[ChatDeps]`の形でtoolの
引数注釈にChatDepsを使うため、実行時に解決できる実importが必要(`from __future__
import annotations`下でもpydantic-aiがtool登録時に`get_type_hints`で解決するため)。
`chat_agent.py`とドメインファイルの双方から素直にimportできるよう、この小さな
専用モジュールに切り出している(`chat_agent.py`がChatDeps/ChatUIStateを持ち、
各ドメインファイルがそれを`from ..chat_agent import ChatDeps`する形にすると、
`chat_agent.py`側もドメインファイルのtool登録関数をimportする必要があるため
循環importになる)。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class ActivePaper(BaseModel):
    """論文モード(015拡張)で「今読んでいる論文」を表す."""

    item_id: str
    title: str


class ChatUIState(BaseModel):
    """AG-UI の RunAgentInput.state ⇄ StateSnapshotEvent で同期する会話状態(015拡張、019で汎用化).

    クライアントは毎ターン `state` をそのまま送り返してくるため、`Agent` の
    `deps_type=StateDeps[ChatUIState]` で受け取り、`get_paper_full_text` が
    成功した時点で `active_paper` をセットする。フロント側はこれを見て
    「📄 読書中: (論文タイトル)」のバッジを表示する。

    `diary_mode`(019-diary-domain)は`active_paper`と独立したフィールドで、両者は
    排他ではなく共存できる(論文について話しながら、その内容を今日の日記にも残せる)。
    元は`PaperModeState`という名前だったが、論文モード専用ではなくなったため改名した。
    """

    active_paper: ActivePaper | None = None
    diary_mode: bool = False


@dataclass
class ChatDeps:
    """メインのチャットエージェントの deps(`StateHandler` プロトコルを満たす自前dataclass).

    `state` は AG-UI の RunAgentInput.state ⇄ StateSnapshotEvent でクライアントと
    同期される(`StateHandler` は「dataclassであること」と「state属性を持つこと」しか
    要求しないため、`pydantic_ai.ui.StateDeps` を使わずこの形で足りる)。`recalled_memory`
    は017-chat-memoryの前処理(`api/app.py`)がサーバー側だけで設定する値で、
    `state` ではないため AG-UI 側には一切公開されない(StateSnapshotEventにも乗らない)。
    """

    state: ChatUIState
    recalled_memory: str | None = None
