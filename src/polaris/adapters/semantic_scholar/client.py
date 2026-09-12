"""Semantic Scholar Academic Graph API への HTTP アクセス(027-related-paper-research).

`adapters/searxng/client.py`と同じ「単一の外部API・薄いhttpxラッパー」方針だが、
Semantic Scholarは無認証だと共有プールのレート制限にかかりやすい(実測: 2026-09-12、
無認証で計7回叩いて成功2回・429が5回、20秒空けても回復しないことがある)。
そのためAPIキーを前提にした上で、全リクエストに指数バックオフを掛ける
(`_get_with_retry`に集約、個別の呼び出し関数には書かない)。

実測で確認した仕様(2026-09-12):

- `GET /paper/{paperId}/references` は `{"data": [{"citedPaper": {...}}]}` の形で、
  参照先の論文情報は `citedPaper` キーでネストする
- `GET /paper/{paperId}/citations` は同様に `citingPaper` キーでネストする
  (内側に `abstract` を含むことを確認済み)
- `openAccessPdf` は存在してもキーが `url: ""` の空文字列で返ることがある
  (`{"url": "", "status": null, "license": null, "disclaimer": "..."}`)
- `GET /paper/arXiv:{arxiv_id}`(単体取得)・`GET /paper/search`(検索)は429により
  未検証。ドキュメント上想定される形(単体オブジェクト/`{"data": [...]}`のフラット)を
  前提にしつつ、寛容なパース(pydanticの未知フィールド無視、ネストしたnull要素の除外)
  に留める
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime as _datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from polaris.settings import SemanticScholarSettings

logger = logging.getLogger(__name__)

# fields パラメータは全エンドポイント共通(未知フィールドはpydantic側で無視するので
# 呼び出し関数ごとに変える必要が無い)。
_FIELDS = "paperId,title,abstract,year,citationCount,externalIds,openAccessPdf"
_RETRYABLE_STATUS_CODES = {429}


class SemanticScholarError(Exception):
    """Semantic Scholar へのリクエストが失敗した場合の例外(リトライを使い切った場合を含む)."""


class _OpenAccessPdf(BaseModel):
    """`openAccessPdf`フィールド(オープンアクセスなPDFへの直リンク、無ければurlが空文字列)."""

    url: str = ""
    status: str | None = None


class SemanticScholarPaper(BaseModel):
    """Semantic Scholarの論文オブジェクトから、027で使う部分だけを抜き出したもの.

    他にも`authors`等の大量のフィールドが返るが未使用のため受け取らない
    (pydanticは既定で未知フィールドを無視する、SearxngResponseと同じ考え方)。
    """

    model_config = ConfigDict(populate_by_name=True)

    paper_id: str = Field(alias="paperId")
    title: str = ""
    abstract: str | None = None
    year: int | None = None
    citation_count: int = Field(default=0, alias="citationCount")
    external_ids: dict[str, Any] | None = Field(default=None, alias="externalIds")
    open_access_pdf: _OpenAccessPdf | None = Field(default=None, alias="openAccessPdf")

    @property
    def arxiv_id(self) -> str | None:
        """`externalIds.ArXiv`があればarXiv IDを返す(無ければNone)."""
        if self.external_ids is None:
            return None
        value = self.external_ids.get("ArXiv")
        return value if isinstance(value, str) else None


class _ReferenceItem(BaseModel):
    """`/references`の`data`配列1件分(参照先論文は`citedPaper`にネストする、nullもありうる)."""

    cited_paper: SemanticScholarPaper | None = Field(default=None, alias="citedPaper")


class _CitationItem(BaseModel):
    """`/citations`の`data`配列1件分(引用元論文は`citingPaper`にネストする、nullもありうる)."""

    citing_paper: SemanticScholarPaper | None = Field(default=None, alias="citingPaper")


class _ReferencesResponse(BaseModel):
    data: list[_ReferenceItem] = []


class _CitationsResponse(BaseModel):
    data: list[_CitationItem] = []


class _SearchResponse(BaseModel):
    """`/paper/search`のレスポンス(未検証のため、要素のnullも許容する寛容なパース)."""

    data: list[SemanticScholarPaper | None] = []


def _parse_retry_after(value: str | None) -> float | None:
    """`Retry-After`ヘッダを秒数へ変換する(秒数形式・HTTP-date形式のどちらも試す)."""
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at is None:
        return None
    delta = (retry_at - _datetime.now(retry_at.tzinfo)).total_seconds()
    return max(delta, 0.0)


async def _sleep_before_retry(
    *,
    attempt: int,
    retry_after: float | None,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> None:
    """指数バックオフ(`Retry-After`があれば優先)+ジッタで待つ."""
    delay = retry_after if retry_after is not None else backoff_base_seconds**attempt
    delay = min(delay, backoff_max_seconds) + random.uniform(0, 1)  # noqa: S311 - 暗号用途ではない
    await asyncio.sleep(delay)


async def _get_with_retry(
    path: str,
    *,
    params: dict[str, str | int],
    client: httpx.AsyncClient,
    settings: SemanticScholarSettings,
) -> httpx.Response:
    """指数バックオフ付きでGETする(唯一のリトライ実装箇所).

    - 429/5xx/`httpx.HTTPError`(タイムアウト・接続エラー含む)はリトライ対象。
      `max_attempts`を使い切ると`SemanticScholarError`を送出する
    - 404はリトライせずそのまま返す(呼び出し側が「見つからない」として扱えるように)
    - 401/403/400等それ以外の4xxは相手の恒久的な拒否とみなし、即座に
      `SemanticScholarError`を送出する(401/403はAPIキー不正の可能性をログに残す)

    Raises:
        SemanticScholarError: リトライを使い切った、または回復不能なエラーの場合。

    """
    url = f"{settings.base_url}{path}"
    attempt = 0
    while True:
        attempt += 1
        try:
            response = await client.get(
                url,
                params=params,
                headers={"x-api-key": settings.api_key},
                timeout=settings.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            if attempt >= settings.max_attempts:
                msg = f"Semantic Scholarへのリクエストに失敗しました(リトライ上限到達): {path}"
                raise SemanticScholarError(msg) from exc
            logger.warning("Semantic Scholar retry %d/%d(接続エラー): path=%s", attempt, settings.max_attempts, path)
            await _sleep_before_retry(
                attempt=attempt,
                retry_after=None,
                backoff_base_seconds=settings.backoff_base_seconds,
                backoff_max_seconds=settings.backoff_max_seconds,
            )
            continue

        if response.status_code == httpx.codes.NOT_FOUND:
            return response

        if response.status_code in _RETRYABLE_STATUS_CODES or response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            if attempt >= settings.max_attempts:
                msg = f"Semantic Scholarへのリクエストに失敗しました(status={response.status_code}): {path}"
                raise SemanticScholarError(msg)
            logger.warning(
                "Semantic Scholar retry %d/%d(status=%d): path=%s",
                attempt,
                settings.max_attempts,
                response.status_code,
                path,
            )
            await _sleep_before_retry(
                attempt=attempt,
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
                backoff_base_seconds=settings.backoff_base_seconds,
                backoff_max_seconds=settings.backoff_max_seconds,
            )
            continue

        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            logger.warning("Semantic Scholar認証エラー(APIキーを確認してください): status=%d", response.status_code)
            msg = f"Semantic Scholarへの認証に失敗しました(status={response.status_code})"
            raise SemanticScholarError(msg)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            msg = f"Semantic Scholarへのリクエストが拒否されました(status={response.status_code}): {path}"
            raise SemanticScholarError(msg)

        return response


async def fetch_paper_by_arxiv_id(
    arxiv_id: str,
    *,
    client: httpx.AsyncClient,
    settings: SemanticScholarSettings,
) -> SemanticScholarPaper | None:
    """ArXiv IDから対応するSemantic Scholarの論文を解決する(見つからなければNone)."""
    response = await _get_with_retry(
        f"/paper/arXiv:{arxiv_id}",
        params={"fields": _FIELDS},
        client=client,
        settings=settings,
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    return SemanticScholarPaper.model_validate_json(response.text)


async def fetch_references(
    paper_id: str,
    *,
    limit: int,
    client: httpx.AsyncClient,
    settings: SemanticScholarSettings,
) -> list[SemanticScholarPaper]:
    """指定論文の参考文献(backward)を返す(ネストが`null`の要素は除外する)."""
    response = await _get_with_retry(
        f"/paper/{paper_id}/references",
        params={"fields": _FIELDS, "limit": limit},
        client=client,
        settings=settings,
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return []
    parsed = _ReferencesResponse.model_validate_json(response.text)
    return [item.cited_paper for item in parsed.data if item.cited_paper is not None]


async def fetch_citations(
    paper_id: str,
    *,
    limit: int,
    client: httpx.AsyncClient,
    settings: SemanticScholarSettings,
) -> list[SemanticScholarPaper]:
    """指定論文を引用している論文(forward)を返す(ネストが`null`の要素は除外する)."""
    response = await _get_with_retry(
        f"/paper/{paper_id}/citations",
        params={"fields": _FIELDS, "limit": limit},
        client=client,
        settings=settings,
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return []
    parsed = _CitationsResponse.model_validate_json(response.text)
    return [item.citing_paper for item in parsed.data if item.citing_paper is not None]


async def search_papers(
    query: str,
    *,
    limit: int,
    client: httpx.AsyncClient,
    settings: SemanticScholarSettings,
) -> list[SemanticScholarPaper]:
    """キーワードでSemantic Scholarを検索する(要素が`null`の場合は除外する)."""
    response = await _get_with_retry(
        "/paper/search",
        params={"query": query, "fields": _FIELDS, "limit": limit},
        client=client,
        settings=settings,
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return []
    parsed = _SearchResponse.model_validate_json(response.text)
    return [paper for paper in parsed.data if paper is not None]
