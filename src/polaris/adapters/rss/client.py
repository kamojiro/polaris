"""RSS 2.0 / Atom フィードの取得・パース(008-daily-digest-domain Phase A).

パース自体は`feedparser`(信頼できる既存実装、RSS/Atomの差異を吸収してくれる)に
任せる。HTTP取得は他のadapter(arxiv/pdf/searxng)と同じくプロジェクト全体で
統一している`httpx`で行い、生バイト列を`feedparser.parse()`に渡す
(feedparser自身のHTTP機能・URL文字列直接渡しは使わない)。
"""

from __future__ import annotations

import asyncio
import logging
import time
from calendar import timegm
from datetime import UTC, datetime

import feedparser
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RssFetchError(Exception):
    """フィードの取得またはパースに失敗した場合の例外."""


class FeedEntry(BaseModel):
    """1件の記事エントリ."""

    title: str
    url: str
    published_at: datetime | None
    summary: str  # フィードのdescription/summary。HTMLタグを含みうるがそのまま渡す


def _parse_entry(entry: feedparser.FeedParserDict) -> FeedEntry | None:
    """feedparserのエントリを`FeedEntry`に変換する.

    title/linkのいずれかが欠けているエントリは記事として不完全なため捨てる(None)。
    公開日時はRSSの`published_parsed`が無いAtomフィードもあるため`updated_parsed`に
    フォールバックする(実機確認: Martin Fowlerのフィードは`published_parsed`が無い)。
    `feedparser.FeedParserDict`は動的な辞書ラッパーで`.get()`の型がUnknown/list型に
    広がってしまうため、`isinstance`で明示的に絞り込む。
    """
    title = entry.get("title")
    url = entry.get("link")
    if not isinstance(title, str) or not isinstance(url, str):
        return None

    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    published_at = (
        datetime.fromtimestamp(timegm(parsed_time), tz=UTC) if isinstance(parsed_time, time.struct_time) else None
    )

    summary = entry.get("summary")
    return FeedEntry(
        title=title,
        url=url,
        published_at=published_at,
        summary=summary if isinstance(summary, str) else "",
    )


async def fetch_feed(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout_seconds: float,
    max_entries: int,
) -> list[FeedEntry]:
    """フィードを取得し、新しい順に先頭`max_entries`件を返す.

    `feedparser.parse()`は同期・ブロッキング呼び出しのため、`asyncio.to_thread()`で
    スレッドに逃がす(`adapters/embeddings/qwen.py`のencode()呼び出しと同じ扱い)。

    Raises:
        RssFetchError: HTTP取得に失敗した場合。

    """
    try:
        # 実機確認(2026-08-26): InfoQ/はてなブックマークは301リダイレクトを返す。
        # httpx はデフォルトでリダイレクトを追わず、raise_for_status() がそれ自体を
        # エラー扱いにするため、明示的に追わせる(adapters/pdf/downloader.pyと同じ扱い)。
        response = await client.get(url, timeout=timeout_seconds, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"フィードの取得に失敗しました: {url}"
        raise RssFetchError(msg) from exc

    parsed = await asyncio.to_thread(feedparser.parse, response.content)
    if parsed.bozo:
        logger.info("feed parsed with warnings (bozo=True): url=%s, reason=%s", url, parsed.get("bozo_exception"))

    return [e for raw in parsed.entries[:max_entries] if (e := _parse_entry(raw)) is not None]
