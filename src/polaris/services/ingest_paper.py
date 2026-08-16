"""ArXiv URL から論文を取り込むユースケース."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from polaris.adapters.arxiv.client import fetch_arxiv_metadata
from polaris.adapters.arxiv.parser import extract_arxiv_id
from polaris.domain.entities import Item, ItemType, PaperRecord

if TYPE_CHECKING:
    import httpx

    from polaris.db.repository import PaperRepository


class InvalidPaperUrlError(Exception):
    """arXiv の URL / ID として解釈できなかった場合の例外."""


async def ingest_paper_from_url(
    url: str,
    *,
    repo: PaperRepository,
    http_client: httpx.AsyncClient,
) -> tuple[Item, PaperRecord, bool]:
    """ArXiv URL からメタデータのみを取得して保存する.

    既に同じ arxiv_id が保存済みであれば再取得せず既存のレコードを返す(冪等)。
    戻り値の bool は新規保存なら True、既存の再利用なら False。
    """
    arxiv_id = extract_arxiv_id(url)
    if arxiv_id is None:
        raise InvalidPaperUrlError(url)

    existing = repo.find_by_arxiv_id(arxiv_id)
    if existing is not None:
        item, record = existing
        return item, record, False

    metadata = await fetch_arxiv_metadata(arxiv_id, client=http_client)

    now = datetime.now(UTC)
    record = PaperRecord(
        id=uuid.uuid4().hex,
        item_id="",  # 直後に確定させる
        authors=metadata.authors,
        year=metadata.year,
        doi=metadata.doi,
        arxiv_id=metadata.arxiv_id,
        abstract=metadata.abstract,
        # ユーザーが貼った生の URL(/pdf/ やバージョン付き)ではなく、
        # 正規化した arxiv_id から組み立てた /abs/ ページに揃える。
        source_url=f"https://arxiv.org/abs/{metadata.arxiv_id}",
        ingested_at=now,
    )
    item = Item(
        id=uuid.uuid4().hex,
        item_type=ItemType.paper,
        title=metadata.title,
        summary=metadata.abstract,
        created_at=now,
        source_ref=f"paper:{record.id}",
    )
    record.item_id = item.id

    repo.save_paper(item, record)
    return item, record, True
