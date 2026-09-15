"""Discordツール(get_discord_reading_list、021-discord-integration「chat経由での利用」).

サイドバー(クリック導線、`GET /api/discord/recent`)とは別に、チャットから能動的に
「ディスコードの内容を教えて」と聞けるようにする。既存の`adapters/discord/client.py`を
そのまま再利用するだけで新規の取得ロジックは無く、永続化もしない(サイドバーと同じ方針)。

メッセージ本文(URLを含むことが多い)をそのまま整形して返し、LLM側に一覧として
まとめさせる(`018-web-search-tool`のweb_search結果整形と同型)。応答にURLが含まれていれば、
続けて`web_fetch`でその中身を取得できる(`018`の「URLを自己推測してはいけない」指示が
ここでも効き、直前の応答に実在するURLだけを使わせる)。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from polaris.adapters.discord.client import DiscordFetchError
from polaris.adapters.discord.client import fetch_recent_messages as discord_fetch_recent_messages

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.adapters.discord.client import DiscordMessage
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
- 「ディスコードの内容を教えて」「後で読むチャンネル見せて」のように尋ねられたら
  get_discord_reading_list ツールを使ってください。結果はメッセージ本文をそのまま
  一覧としてまとめて答えてください(要約しすぎず、URLがあれば省略しないこと)。
- 一覧の中から特定の1件について詳しく聞かれたら、その本文に含まれるURLを引数に
  web_fetch を呼んで中身を取得してください。URLは直前の応答に実際に登場した
  文字列そのものを使い、自分で推測・生成したURLを渡してはいけません。"""


def _format_reading_list(messages: list[DiscordMessage]) -> str:
    """get_discord_reading_list の戻り値を組み立てる(著者・本文をそのまま列挙)."""
    if not messages:
        return "「後で読む」チャンネルにメッセージが見つかりませんでした。"

    lines = [f"{i}. {m.author_name}: {m.content}" for i, m in enumerate(messages, start=1)]
    return "# Discord「後で読む」チャンネルの最近のメッセージ\n\n" + "\n".join(lines)


def register(agent: Agent[Any, Any], *, settings: Settings) -> None:
    """get_discord_reading_list ツールを登録する(021-discord-integration).

    `agent.tool_plain`はRunContext/depsに触れないため、`web_search.register`と同じ形で
    deps_type/output_typeを問わず任意のAgentに登録できる。
    """
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def get_discord_reading_list() -> str:
        """Discordの「後で読む」チャンネルの最近のメッセージ一覧を取得する.

        Returns:
            著者・本文(URLを含む)をそのまま列挙した文字列
            (未設定・失敗時はその旨の日本語メッセージ)。

        """
        logger.info("tool call: get_discord_reading_list()")
        if not settings.discord.bot_token or not settings.discord.channel_id:
            return "Discord連携機能は現在無効です(bot_token/channel_idが未設定のため)。"
        try:
            messages = await discord_fetch_recent_messages(
                client=http_client,
                bot_token=settings.discord.bot_token,
                channel_id=settings.discord.channel_id,
                limit=settings.discord.max_messages,
                timeout_seconds=settings.discord.timeout_seconds,
            )
        except DiscordFetchError:
            logger.exception("get_discord_reading_list failed")
            return "Discordのメッセージ取得に失敗しました。チャンネルに接続できないか、一時的な問題が発生しています。"
        return _format_reading_list(messages)
