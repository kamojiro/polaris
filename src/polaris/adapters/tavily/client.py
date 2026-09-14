"""Tavily検索APIへの検索HTTPアクセス(018-web-search-tool、2026-09-14にSearXNGから移行).

自前ホスト済みSearXNGは検索結果の質(関連度・情報の新しさ)が不十分だったため、
LLM向けに作られたホスト型の検索API(Tavily)に切り替えた。`adapters/searxng/client.py`と
同じ「薄いhttpxクライアントを自前で書く」方針は変えない(018の「接続方式」参照)。

Tavily API(2026-09-14時点でのドキュメント確認)の仕様:

- `POST https://api.tavily.com/search`、認証は`Authorization: Bearer <api_key>`ヘッダー
- リクエストボディ(JSON): `query`(必須)・`max_results`(既定10、最大20)・
  `include_answer`(LLM生成の要約回答を含めるか)。SearXNGと違い`max_results`は
  リクエスト側で効くため、SearXNG版のような「多めに取得してクライアント側で
  先頭N件に切り詰める」処理は不要
- レスポンス(JSON): `answer`(LLM生成の短い回答、`include_answer=false`ならnull)・
  `results`(`title`/`url`/`content`/`score`等を持つ配列、関連度順)
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

_SEARCH_PATH = "/search"


class TavilySearchError(Exception):
    """Tavilyへの検索リクエストが失敗した場合の例外."""


class SearchResult(BaseModel):
    """Tavilyの`results`配列の1件.

    Tavilyは他にも`published_date`/`favicon`等のフィールドを返すが、LLMに渡す
    情報として不要なため受け取らない(pydanticは既定で未知フィールドを無視する)。
    """

    title: str
    url: str
    content: str = ""


class TavilyResponse(BaseModel):
    """Tavilyの`/search`レスポンスから、LLMに渡す部分だけを抜き出したもの."""

    answer: str | None = None
    results: list[SearchResult] = []


async def search(
    query: str,
    *,
    client: httpx.AsyncClient,
    api_key: str,
    base_url: str,
    max_results: int,
    timeout_seconds: float,
    include_answer: bool,
) -> TavilyResponse:
    """Tavilyに検索クエリを投げ、上位`max_results`件の結果を返す.

    Raises:
        TavilySearchError: HTTPリクエストが失敗した場合。

    """
    try:
        response = await client.post(
            f"{base_url}{_SEARCH_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": query, "max_results": max_results, "include_answer": include_answer},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"Tavilyへの検索リクエストに失敗しました: {query!r}"
        raise TavilySearchError(msg) from exc

    return TavilyResponse.model_validate_json(response.text)
