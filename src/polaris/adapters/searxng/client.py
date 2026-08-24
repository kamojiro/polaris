"""自前ホスト済み SearXNG インスタンスへの検索 HTTP アクセス(018-web-search-tool).

MCP toolset(サードパーティのサブプロセス)は経由しない方針転換をした(spec の
「背景・判断」参照)。SearXNG の検索エンドポイントは `GET /search?format=json` 1本・
認証不要という単純な API のため、`adapters/pdf/downloader.py` と同じ形で薄い
httpx クライアントを自前で書く。

実機(`http://127.0.0.1:8080`)に対する実測で確認した仕様:

- `number_of_results` は常に `0` が返る(SearXNG でよくある挙動)ため信用できない。
  件数は `len(results)` を使う。ここでは誤用の余地を残さないためモデルに含めない
- `results` は既に `score` の降順でソート済みなので、先頭 N 件を取れば上位の結果になる
- `answers`(検索エンジンの instant answer)・`infoboxes`(Wikipedia 等の要約)は
  情報密度が高く、含めるコストもほぼゼロなので一緒に返す
- `unresponsive_engines`(落ちている検索エンジンの一覧)は運用情報であり LLM には
  渡さない意味が無いため、ログに出すだけに留める
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SEARCH_PATH = "/search"


class SearxngSearchError(Exception):
    """SearXNG への検索リクエストが失敗した場合の例外."""


class SearchResult(BaseModel):
    """SearXNG の `results` 配列の1件.

    SearXNG は他にも `template`/`positions`/`thumbnail` 等の大量のフィールドを
    返すが、LLM に渡す情報として不要なため受け取らない(pydantic は既定で
    未知フィールドを無視する)。
    """

    title: str
    url: str
    content: str = ""
    engine: str = ""


class Answer(BaseModel):
    """検索エンジンの instant answer(`answers` 配列の1件)."""

    answer: str
    url: str = ""


class Infobox(BaseModel):
    """Wikipedia 等の要約ボックス(`infoboxes` 配列の1件)."""

    infobox: str
    content: str = ""


class SearxngResponse(BaseModel):
    """SearXNG の `/search?format=json` レスポンスから、LLM に渡す部分だけを抜き出したもの."""

    results: list[SearchResult] = []
    answers: list[Answer] = []
    infoboxes: list[Infobox] = []
    unresponsive_engines: list[list[str]] = []


async def search(
    query: str,
    *,
    client: httpx.AsyncClient,
    base_url: str,
    max_results: int,
    timeout_seconds: float,
) -> SearxngResponse:
    """SearXNG に検索クエリを投げ、結果を上位 `max_results` 件に絞って返す.

    Raises:
        SearxngSearchError: HTTP リクエストが失敗した場合。

    """
    try:
        response = await client.get(
            f"{base_url}{_SEARCH_PATH}",
            params={"q": query, "format": "json"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"SearXNGへの検索リクエストに失敗しました: {query!r}"
        raise SearxngSearchError(msg) from exc

    parsed = SearxngResponse.model_validate_json(response.text)
    if parsed.unresponsive_engines:
        logger.info("SearXNG unresponsive engines: %s", parsed.unresponsive_engines)
    return parsed.model_copy(update={"results": parsed.results[:max_results]})
