"""adapters/discord/client.py のテスト.

SearXNGクライアントのテストと違い実機採取のfixtureは使えないため、Discord公式ドキュメントの
メッセージオブジェクトの形(`id`/`content`/`author.username`/`timestamp`)に基づく手組みの
JSONを使う。
"""

import httpx
import pytest
import respx

from polaris.adapters.discord.client import DiscordFetchError, fetch_recent_messages

_CHANNEL_ID = "1111111111111111111"
_MESSAGES_URL = f"https://discord.com/api/v10/channels/{_CHANNEL_ID}/messages"
_FAKE_BOT_TOKEN = "fake-token"  # noqa: S105 テスト用のダミー値(実際の認証情報ではない)


@pytest.mark.asyncio
async def test_fetch_recent_messages_parses_id_content_author_timestamp() -> None:
    """id/content/author.username/timestampがパースできる."""
    body = [
        {
            "id": "222",
            "content": "arXivの新しい論文が良さそう https://arxiv.org/abs/1234.5678",
            "author": {"id": "999", "username": "kamojiro"},
            "timestamp": "2026-09-02T12:00:00.000000+00:00",
            "embeds": [],
            "attachments": [],
        }
    ]
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(_MESSAGES_URL).mock(return_value=httpx.Response(200, json=body))

        messages = await fetch_recent_messages(
            client=client, bot_token=_FAKE_BOT_TOKEN, channel_id=_CHANNEL_ID, limit=5, timeout_seconds=10.0
        )

    assert len(messages) == 1
    assert messages[0].id == "222"
    assert messages[0].content == "arXivの新しい論文が良さそう https://arxiv.org/abs/1234.5678"
    assert messages[0].author_name == "kamojiro"
    assert messages[0].created_at.year == 2026  # noqa: PLR2004


@pytest.mark.asyncio
async def test_fetch_recent_messages_sends_bot_token_and_limit() -> None:
    """Authorizationヘッダとlimitクエリパラメータが正しく送信される."""
    async with httpx.AsyncClient() as client, respx.mock:
        route = respx.get(_MESSAGES_URL).mock(return_value=httpx.Response(200, json=[]))

        await fetch_recent_messages(
            client=client, bot_token=_FAKE_BOT_TOKEN, channel_id=_CHANNEL_ID, limit=3, timeout_seconds=10.0
        )

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bot {_FAKE_BOT_TOKEN}"
    assert request.url.params["limit"] == "3"


@pytest.mark.asyncio
async def test_fetch_recent_messages_returns_empty_list_when_no_messages() -> None:
    """メッセージが1件も無ければ空リストを返す."""
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(_MESSAGES_URL).mock(return_value=httpx.Response(200, json=[]))

        messages = await fetch_recent_messages(
            client=client, bot_token=_FAKE_BOT_TOKEN, channel_id=_CHANNEL_ID, limit=5, timeout_seconds=10.0
        )

    assert messages == []


@pytest.mark.asyncio
async def test_fetch_recent_messages_raises_on_http_error() -> None:
    """Discordが401/403等のHTTPエラーを返したらDiscordFetchErrorを送出する."""
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(_MESSAGES_URL).mock(return_value=httpx.Response(401))

        with pytest.raises(DiscordFetchError):
            await fetch_recent_messages(
                client=client, bot_token=_FAKE_BOT_TOKEN, channel_id=_CHANNEL_ID, limit=5, timeout_seconds=10.0
            )
