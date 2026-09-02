"""Discord REST APIから指定チャンネルの直近メッセージを取得する(021-discord-integration 方向性3).

`adapters/searxng/client.py`と同じ「単一エンドポイント・簡単なAPIキー程度なら自前adapter」
判断に基づく薄いhttpxラッパー(`specs/IDEAS.md`の「MCP vs 自前adapter」判断基準)。
`~/study/summarizer`の実装(discord.pyの常時接続gatewayクライアント)とは異なり、
gateway接続は持たず、REST APIを都度叩くだけの読み取り専用・ステートレスな実装にする
(bot自体をDiscordサーバーに常駐させる必要が無く、特権インテントの申請も不要)。
"""

from __future__ import annotations

# DiscordMessage/_RawDiscordMessage の datetime フィールドは pydantic が実行時に
# get_type_hints() で解決するため、TYPE_CHECKING ブロックに入れると NameError になる
# (`from __future__ import annotations` で文字列注釈になるため)。ruff の TC003 は意図的に無視する。
from datetime import datetime  # noqa: TC003

import httpx
from pydantic import BaseModel

_API_BASE = "https://discord.com/api/v10"


class DiscordFetchError(Exception):
    """Discordへのメッセージ取得リクエストが失敗した場合の例外."""


class DiscordMessage(BaseModel):
    """Discordメッセージから、サイドバー表示に使う部分だけを抜き出したもの."""

    id: str
    content: str
    author_name: str
    created_at: datetime


class _DiscordAuthor(BaseModel):
    """Discord APIが返すメッセージの`author`オブジェクト(必要なフィールドのみ)."""

    username: str


class _RawDiscordMessage(BaseModel):
    """Discord APIの`GET /channels/{channel_id}/messages`レスポンス1件分(生の形).

    Discordは他にも`embeds`/`attachments`/`mentions`等の大量のフィールドを返すが、
    サイドバー表示に不要なため受け取らない(pydanticは既定で未知フィールドを無視する、
    SearxngResponseと同じ考え方)。
    """

    id: str
    content: str
    author: _DiscordAuthor
    timestamp: datetime


async def fetch_recent_messages(
    *,
    client: httpx.AsyncClient,
    bot_token: str,
    channel_id: str,
    limit: int,
    timeout_seconds: float,
) -> list[DiscordMessage]:
    """指定チャンネルの直近`limit`件のメッセージを新しい順のまま返す(Discord APIの既定順).

    Raises:
        DiscordFetchError: HTTP リクエストが失敗した場合。

    """
    try:
        response = await client.get(
            f"{_API_BASE}/channels/{channel_id}/messages",
            params={"limit": limit},
            headers={"Authorization": f"Bot {bot_token}"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"Discordチャンネル{channel_id!r}のメッセージ取得に失敗しました"
        raise DiscordFetchError(msg) from exc

    raw_messages = [_RawDiscordMessage.model_validate(item) for item in response.json()]
    return [
        DiscordMessage(id=m.id, content=m.content, author_name=m.author.username, created_at=m.timestamp)
        for m in raw_messages
    ]
