"""load_full_text(015-paper-qa-chat)の純ロジックテスト.

実LLMは使わず、実際の PdfExtractionError を確認できるよう
tests/adapters/fixtures 配下の実PDF(attention.pdf/corrupt.pdf)を使う。
"""

from datetime import UTC, datetime
from pathlib import Path

from polaris.domain.entities import Item, ItemType, PaperRecord
from polaris.services.paper_full_text import load_full_text

_FIXTURE_DIR = Path(__file__).parent.parent / "adapters" / "fixtures"


def _make_paper(*, pdf_path: str | None, text_path: str | None = None) -> tuple[Item, PaperRecord]:
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
        text_path=text_path,
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


async def test_load_full_text_extracts_from_pdf() -> None:
    """pdf_path が有効な場合、PDFから本文を再抽出する."""
    item, record = _make_paper(pdf_path=str(_FIXTURE_DIR / "attention.pdf"))

    result = await load_full_text(item, record, max_chars=1_000_000)

    assert result.from_pdf is True
    assert result.truncated is False
    assert "Attention" in result.text


async def test_load_full_text_falls_back_to_text_path_when_pdf_missing(tmp_path: Path) -> None:
    """pdf_path が None の場合、永続化済み全文ファイル(text_path)を読む."""
    text_path = tmp_path / "1706.03762.txt"
    text_path.write_text("persisted full text body", encoding="utf-8")
    item, record = _make_paper(pdf_path=None, text_path=str(text_path))

    result = await load_full_text(item, record, max_chars=1_000_000)

    assert result.from_pdf is False
    assert "persisted full text body" in result.text


async def test_load_full_text_falls_back_to_text_path_when_pdf_corrupt(tmp_path: Path) -> None:
    """PDFの読み込みに失敗した場合(PdfExtractionError)も永続化済み全文ファイルにフォールバックする."""
    text_path = tmp_path / "1706.03762.txt"
    text_path.write_text("text from fallback file", encoding="utf-8")
    item, record = _make_paper(pdf_path=str(_FIXTURE_DIR / "corrupt.pdf"), text_path=str(text_path))

    result = await load_full_text(item, record, max_chars=1_000_000)

    assert result.from_pdf is False
    assert "text from fallback file" in result.text


async def test_load_full_text_falls_back_to_summary_when_no_text_path() -> None:
    """pdf_path も text_path も無い場合(text_path追加より前にIngestした論文等)、item.summaryに落ちる."""
    item, record = _make_paper(pdf_path=None, text_path=None)

    result = await load_full_text(item, record, max_chars=1_000_000)

    assert result.from_pdf is False
    assert result.text == "fallback summary"


async def test_load_full_text_truncates_when_over_max_chars(tmp_path: Path) -> None:
    """max_chars を超えると切り詰められ、truncated=True になる."""
    text_path = tmp_path / "1706.03762.txt"
    text_path.write_text("x" * 100, encoding="utf-8")
    item, record = _make_paper(pdf_path=None, text_path=str(text_path))

    result = await load_full_text(item, record, max_chars=10)

    assert result.truncated is True
    assert len(result.text) == 10  # noqa: PLR2004
