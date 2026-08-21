"""load_full_text(015-paper-qa-chat)の純ロジックテスト.

実LLMは使わず、実際の PdfExtractionError を確認できるよう
tests/adapters/fixtures 配下の実PDF(attention.pdf/corrupt.pdf)を使う。
"""

from datetime import UTC, datetime
from pathlib import Path

from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import Chunk, Item, ItemType, PaperRecord
from polaris.services.paper_full_text import load_full_text

_FIXTURE_DIR = Path(__file__).parent.parent / "adapters" / "fixtures"


def _make_paper(*, pdf_path: str | None) -> tuple[Item, PaperRecord]:
    now = datetime.now(UTC)
    record = PaperRecord(
        id="rec-1",
        item_id="item-1",
        authors=["Fake Author"],
        year=2024,
        arxiv_id="1706.03762",
        abstract="fallback abstract",
        source_url="https://arxiv.org/abs/1706.03762",
        pdf_path=pdf_path,
        ingested_at=now,
    )
    item = Item(
        id="item-1",
        item_type=ItemType.paper,
        title="Attention Is All You Need",
        summary="fallback summary",
        created_at=now,
        source_ref="paper:rec-1",
    )
    return item, record


async def test_load_full_text_extracts_from_pdf(tmp_path: Path) -> None:
    """pdf_path が有効な場合、PDFから本文を再抽出する."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper(pdf_path=str(_FIXTURE_DIR / "attention.pdf"))
    repo.save_paper(item, record)

    result = await load_full_text(item, record, repo=repo, max_chars=1_000_000)

    assert result.from_pdf is True
    assert result.truncated is False
    assert "Attention" in result.text


async def test_load_full_text_falls_back_to_chunks_when_pdf_missing(tmp_path: Path) -> None:
    """pdf_path が None の場合、保存済みチャンクを連結してフォールバックする."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper(pdf_path=None)
    repo.save_paper(item, record)
    repo.save_chunks(
        [
            Chunk(id="c1", item_id=item.id, section=None, order=0, text="first chunk"),
            Chunk(id="c2", item_id=item.id, section=None, order=1, text="second chunk"),
        ]
    )

    result = await load_full_text(item, record, repo=repo, max_chars=1_000_000)

    assert result.from_pdf is False
    assert "first chunk" in result.text
    assert "second chunk" in result.text


async def test_load_full_text_falls_back_to_chunks_when_pdf_corrupt(tmp_path: Path) -> None:
    """PDFの読み込みに失敗した場合(PdfExtractionError)もチャンク連結にフォールバックする."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper(pdf_path=str(_FIXTURE_DIR / "corrupt.pdf"))
    repo.save_paper(item, record)
    repo.save_chunks([Chunk(id="c1", item_id=item.id, section=None, order=0, text="chunk from fallback")])

    result = await load_full_text(item, record, repo=repo, max_chars=1_000_000)

    assert result.from_pdf is False
    assert "chunk from fallback" in result.text


async def test_load_full_text_truncates_when_over_max_chars(tmp_path: Path) -> None:
    """max_chars を超えると切り詰められ、truncated=True になる."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper(pdf_path=None)
    repo.save_paper(item, record)
    repo.save_chunks([Chunk(id="c1", item_id=item.id, section=None, order=0, text="x" * 100)])

    result = await load_full_text(item, record, repo=repo, max_chars=10)

    assert result.truncated is True
    assert len(result.text) == 10  # noqa: PLR2004
