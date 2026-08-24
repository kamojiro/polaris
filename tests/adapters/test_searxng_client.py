"""adapters/searxng/client.py のテスト.

`fixture_searxng.json` は実機の SearXNG(http://127.0.0.1:8080)に
「Attention Is All You Need」で実際にクエリを投げて取得したレスポンスをそのまま
固定化したもの(018-web-search-tool 実装時に採取)。SearXNG が返す大量の未知
フィールド(`template`/`positions`/`thumbnail` 等)を含んだ本物の形で、パースが
壊れないことを検証する。
"""

from pathlib import Path

import httpx
import pytest
import respx

from polaris.adapters.searxng.client import SearxngSearchError, search

_FIXTURE_DIR = Path(__file__).parent
_SEARXNG_JSON = (_FIXTURE_DIR / "fixture_searxng.json").read_text(encoding="utf-8")
_BASE_URL = "http://127.0.0.1:8080"


@pytest.mark.asyncio
async def test_search_parses_results_from_real_fixture() -> None:
    """Results 配列の title/url/content/engine がパースできる."""
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(f"{_BASE_URL}/search").mock(return_value=httpx.Response(200, text=_SEARXNG_JSON))

        response = await search(
            "Attention Is All You Need", client=client, base_url=_BASE_URL, max_results=5, timeout_seconds=10.0
        )

    assert len(response.results) == 5  # noqa: PLR2004 max_results=5 で絞られる(フィクスチャは10件)
    first = response.results[0]
    assert first.title == "[1706.03762] Attention Is All You Need - arXiv.org"
    assert first.url == "https://arxiv.org/abs/1706.03762"
    assert "Transformer" in first.content
    assert first.engine == "duckduckgo"


@pytest.mark.asyncio
async def test_search_parses_answers_and_infoboxes() -> None:
    """answers/infoboxes(検索エンジンの回答・要約)がパースできる."""
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(f"{_BASE_URL}/search").mock(return_value=httpx.Response(200, text=_SEARXNG_JSON))

        response = await search("query", client=client, base_url=_BASE_URL, max_results=5, timeout_seconds=10.0)

    assert len(response.answers) == 1
    assert "transformer" in response.answers[0].answer
    assert response.answers[0].url == "https://en.wikipedia.org/wiki/Attention_Is_All_You_Need"

    assert len(response.infoboxes) == 1
    assert response.infoboxes[0].infobox == "Attention Is All You Need"


@pytest.mark.asyncio
async def test_search_truncates_to_max_results() -> None:
    """Results は max_results で先頭から切り詰められる(フィクスチャは10件)."""
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(f"{_BASE_URL}/search").mock(return_value=httpx.Response(200, text=_SEARXNG_JSON))

        response = await search("query", client=client, base_url=_BASE_URL, max_results=2, timeout_seconds=10.0)

    assert len(response.results) == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_search_returns_empty_results_when_none_found() -> None:
    """results/answers/infoboxes がすべて空でも例外にならず空リストが返る."""
    empty_body = '{"query": "no hits", "number_of_results": 0, "results": [], "answers": [], "infoboxes": []}'
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(f"{_BASE_URL}/search").mock(return_value=httpx.Response(200, text=empty_body))

        response = await search("no hits", client=client, base_url=_BASE_URL, max_results=5, timeout_seconds=10.0)

    assert response.results == []
    assert response.answers == []
    assert response.infoboxes == []


@pytest.mark.asyncio
async def test_search_raises_on_http_error() -> None:
    """SearXNGがHTTPエラーを返したら SearxngSearchError を送出する."""
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get(f"{_BASE_URL}/search").mock(return_value=httpx.Response(500))

        with pytest.raises(SearxngSearchError):
            await search("query", client=client, base_url=_BASE_URL, max_results=5, timeout_seconds=10.0)
