"""ingest_paper_from_url の冪等性・エラーハンドリングのテスト."""

from pathlib import Path

import httpx
import pytest
import respx

from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.services.ingest_paper import InvalidPaperUrlError, ingest_paper_from_url

_FIXTURE = (Path(__file__).parent.parent / "adapters" / "fixture_1706.03762.xml").read_text(encoding="utf-8")
_URL = "https://arxiv.org/abs/1706.03762"


async def test_ingest_paper_saves_metadata_only(tmp_path: Path) -> None:
    """ArXiv URL から Item + PaperRecord が保存される(本文抽出はしない)."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))

    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=_FIXTURE),
        )
        async with httpx.AsyncClient() as client:
            item, record, created = await ingest_paper_from_url(_URL, repo=repo, http_client=client)

    assert created is True
    assert item.title == "Attention Is All You Need"
    assert record.arxiv_id == "1706.03762"
    assert len(repo.list_papers()) == 1


async def test_ingest_paper_normalizes_source_url_to_abs(tmp_path: Path) -> None:
    """貼られた URL の形(/pdf/・バージョン付き)によらず source_url は /abs/ に揃う."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    pasted_url = "https://arxiv.org/pdf/1706.03762v7"

    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=_FIXTURE),
        )
        async with httpx.AsyncClient() as client:
            _, record, _ = await ingest_paper_from_url(pasted_url, repo=repo, http_client=client)

    assert record.source_url == "https://arxiv.org/abs/1706.03762"


async def test_ingest_paper_is_idempotent(tmp_path: Path) -> None:
    """同じ ArXiv URL を2回投げても重複登録されない."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))

    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=_FIXTURE),
        )
        async with httpx.AsyncClient() as client:
            first_item, _, first_created = await ingest_paper_from_url(_URL, repo=repo, http_client=client)
            second_item, _, second_created = await ingest_paper_from_url(_URL, repo=repo, http_client=client)

    assert first_created is True
    assert second_created is False
    assert first_item.id == second_item.id
    assert len(repo.list_papers()) == 1


async def test_ingest_paper_rejects_non_arxiv_url(tmp_path: Path) -> None:
    """ArXiv の URL / ID として解釈できない入力は InvalidPaperUrlError になる."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))

    async with httpx.AsyncClient() as client:
        with pytest.raises(InvalidPaperUrlError):
            await ingest_paper_from_url("https://example.com/not-a-paper", repo=repo, http_client=client)
