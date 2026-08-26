"""adapters/rss/client.py のテスト.

`fixture_rss.xml`/`fixture_atom.xml` はそれぞれ実機(hnrss.org / martinfowler.com)から
実際に取得したRSS 2.0 / Atomフィードをそのまま固定化したもの(008-daily-digest-domain
Phase A実装時に採取)。本物の形でパースが壊れないことを検証する。
"""

from pathlib import Path

import httpx
import pytest
import respx

from polaris.adapters.rss.client import RssFetchError, fetch_feed

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_RSS_BYTES = (_FIXTURE_DIR / "feed_rss.xml").read_bytes()
_ATOM_BYTES = (_FIXTURE_DIR / "feed_atom.xml").read_bytes()
_URL = "https://example.com/feed"


async def test_fetch_feed_parses_rss2_entries() -> None:
    """RSS 2.0形式のフィード(hnrss.org実測)からtitle/url/公開日時/summaryを取得できる."""
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, content=_RSS_BYTES))
        async with httpx.AsyncClient() as client:
            entries = await fetch_feed(_URL, client=client, timeout_seconds=10.0, max_entries=20)

    assert len(entries) > 0
    first = entries[0]
    assert first.title != ""
    assert first.url.startswith("http")
    assert first.published_at is not None


async def test_fetch_feed_parses_atom_entries() -> None:
    """Atom形式のフィード(martinfowler.com実測)からtitle/urlを取得できる.

    実機確認: このフィードは`published_parsed`が無く`updated_parsed`のみ持つ
    (Atomフィード全般で起こりうる)。それでも公開日時が取れることを検証する。
    """
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, content=_ATOM_BYTES))
        async with httpx.AsyncClient() as client:
            entries = await fetch_feed(_URL, client=client, timeout_seconds=10.0, max_entries=20)

    assert len(entries) > 0
    first = entries[0]
    assert first.title != ""
    assert first.url.startswith("http")
    assert first.published_at is not None  # updated_parsed へのフォールバックが効く


async def test_fetch_feed_truncates_to_max_entries() -> None:
    """max_entriesで件数が絞られる(hnrss.orgのフィクスチャは20件超)."""
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, content=_RSS_BYTES))
        async with httpx.AsyncClient() as client:
            entries = await fetch_feed(_URL, client=client, timeout_seconds=10.0, max_entries=3)

    assert len(entries) == 3  # noqa: PLR2004 max_entries=3 で絞られる


async def test_fetch_feed_raises_on_http_error() -> None:
    """フィード取得がHTTPエラーになった場合は RssFetchError を送出する."""
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            with pytest.raises(RssFetchError):
                await fetch_feed(_URL, client=client, timeout_seconds=10.0, max_entries=20)


async def test_fetch_feed_returns_empty_list_for_empty_feed() -> None:
    """エントリが1件も無い(不完全な)フィードでも例外にならず空リストを返す."""
    empty_rss = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>"""
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, content=empty_rss))
        async with httpx.AsyncClient() as client:
            entries = await fetch_feed(_URL, client=client, timeout_seconds=10.0, max_entries=20)

    assert entries == []
