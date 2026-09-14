"""adapters/tavily/client.py のテスト.

Tavily公式ドキュメント(2026-09-14確認)のレスポンス例に基づいた合成フィクスチャで検証する
(SearXNGと違い自前ホストしていないため、実機採取のフィクスチャは用意できない)。
"""

import httpx
import pytest
import respx

from polaris.adapters.tavily.client import TavilySearchError, search

_BASE_URL = "https://api.tavily.com"
_API_KEY = "tvly-test-key"

_RESPONSE_BODY = """
{
  "query": "Attention Is All You Need",
  "answer": "\\"Attention Is All You Need\\" is the 2017 paper that introduced the Transformer architecture.",
  "results": [
    {
      "title": "[1706.03762] Attention Is All You Need",
      "url": "https://arxiv.org/abs/1706.03762",
      "content": "The dominant sequence transduction models are based on complex recurrent networks.",
      "score": 0.91,
      "published_date": "2017-06-12"
    },
    {
      "title": "Attention Is All You Need - Wikipedia",
      "url": "https://en.wikipedia.org/wiki/Attention_Is_All_You_Need",
      "content": "A 2017 landmark research paper in machine learning.",
      "score": 0.73
    }
  ],
  "response_time": 1.2
}
"""


async def test_search_parses_answer_and_results() -> None:
    """answer・results配列のtitle/url/contentがパースできる(未知フィールドは無視)."""
    async with httpx.AsyncClient() as client, respx.mock:
        route = respx.post(f"{_BASE_URL}/search").mock(return_value=httpx.Response(200, text=_RESPONSE_BODY))

        response = await search(
            "Attention Is All You Need",
            client=client,
            api_key=_API_KEY,
            base_url=_BASE_URL,
            max_results=5,
            timeout_seconds=10.0,
            include_answer=True,
        )

    assert response.answer is not None
    assert "Transformer" in response.answer
    assert len(response.results) == 2  # noqa: PLR2004
    assert response.results[0].title == "[1706.03762] Attention Is All You Need"
    assert response.results[0].url == "https://arxiv.org/abs/1706.03762"
    assert "recurrent" in response.results[0].content

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {_API_KEY}"
    assert request.method == "POST"


async def test_search_sends_max_results_and_include_answer_in_body() -> None:
    """max_results/include_answerがリクエストボディに載る(SearXNGと違いサーバー側で効く)."""
    async with httpx.AsyncClient() as client, respx.mock:
        route = respx.post(f"{_BASE_URL}/search").mock(return_value=httpx.Response(200, text=_RESPONSE_BODY))

        await search(
            "query",
            client=client,
            api_key=_API_KEY,
            base_url=_BASE_URL,
            max_results=3,
            timeout_seconds=10.0,
            include_answer=False,
        )

    body = route.calls.last.request.content
    assert b'"max_results":3' in body
    assert b'"include_answer":false' in body


async def test_search_returns_empty_results_when_none_found() -> None:
    """resultsが空・answerがnullでも例外にならない."""
    empty_body = '{"query": "no hits", "answer": null, "results": []}'
    async with httpx.AsyncClient() as client, respx.mock:
        respx.post(f"{_BASE_URL}/search").mock(return_value=httpx.Response(200, text=empty_body))

        response = await search(
            "no hits",
            client=client,
            api_key=_API_KEY,
            base_url=_BASE_URL,
            max_results=5,
            timeout_seconds=10.0,
            include_answer=True,
        )

    assert response.answer is None
    assert response.results == []


async def test_search_raises_on_http_error() -> None:
    """TavilyがHTTPエラーを返したらTavilySearchErrorを送出する."""
    async with httpx.AsyncClient() as client, respx.mock:
        respx.post(f"{_BASE_URL}/search").mock(return_value=httpx.Response(401))

        with pytest.raises(TavilySearchError):
            await search(
                "query",
                client=client,
                api_key=_API_KEY,
                base_url=_BASE_URL,
                max_results=5,
                timeout_seconds=10.0,
                include_answer=True,
            )
