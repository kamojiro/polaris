"""ArXiv API への HTTP アクセス."""

from __future__ import annotations

from typing import TYPE_CHECKING

from polaris.adapters.arxiv.parser import ArxivMetadata, parse_atom_entry

if TYPE_CHECKING:
    import httpx

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_TIMEOUT_SECONDS = 15.0


async def fetch_arxiv_metadata(arxiv_id: str, *, client: httpx.AsyncClient) -> ArxivMetadata:
    """arxiv_id をもとに arXiv API からメタデータを取得する.

    取得・パースに失敗した場合は例外を送出し、呼び出し側で Ingest 全体を失敗させる
    (002-papers-ingest-full のエラーハンドリング方針と揃える)。
    """
    response = await client.get(
        _ARXIV_API_URL,
        params={"id_list": arxiv_id, "max_results": 1},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return parse_atom_entry(response.text)
