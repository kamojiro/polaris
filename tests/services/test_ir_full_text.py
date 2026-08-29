"""load_ir_full_text(013-ir-analysis-domain)の純ロジックテスト.

tests/services/test_paper_full_text.py と同じ形を踏襲する。実LLMは使わず、
tests/adapters/fixtures 配下の実PDF(attention.pdf/corrupt.pdf)を使う。
IR文書はv1でChunkを作らないため、フォールバック先は Item.summary のみ。
"""

from datetime import UTC, datetime
from pathlib import Path

from polaris.domain.entities import IrRecord, Item, ItemType
from polaris.services.ir_full_text import load_ir_full_text

_FIXTURE_DIR = Path(__file__).parent.parent / "adapters" / "fixtures"


def _make_ir_document(*, pdf_path: str | None) -> tuple[Item, IrRecord]:
    now = datetime.now(UTC)
    record = IrRecord(
        id="rec-1",
        item_id="item-1",
        doc_id="S100XXXX",
        filer_name="テスト株式会社",
        edinet_code="E00001",
        doc_type_code="有価証券報告書",
        period_start=None,
        period_end=None,
        submit_datetime=now,
        pdf_path=pdf_path,
        ingested_at=now,
    )
    item = Item(
        id="item-1",
        item_type=ItemType.ir_document,
        title="テスト株式会社 有価証券報告書",
        summary="fallback summary",
        created_at=now,
        source_ref="ir_document:rec-1",
    )
    return item, record


async def test_load_ir_full_text_extracts_from_pdf() -> None:
    """pdf_path が有効な場合、PDFから本文を再抽出する."""
    item, record = _make_ir_document(pdf_path=str(_FIXTURE_DIR / "attention.pdf"))

    result = await load_ir_full_text(item, record, max_chars=1_000_000)

    assert result.from_pdf is True
    assert result.truncated is False
    assert "Attention" in result.text


async def test_load_ir_full_text_falls_back_to_summary_when_pdf_missing() -> None:
    """pdf_path が None の場合、Item.summary にフォールバックする(v1はChunkが無いため)."""
    item, record = _make_ir_document(pdf_path=None)

    result = await load_ir_full_text(item, record, max_chars=1_000_000)

    assert result.from_pdf is False
    assert result.text == "fallback summary"


async def test_load_ir_full_text_falls_back_to_summary_when_pdf_corrupt() -> None:
    """PDFの読み込みに失敗した場合(PdfExtractionError)も Item.summary にフォールバックする."""
    item, record = _make_ir_document(pdf_path=str(_FIXTURE_DIR / "corrupt.pdf"))

    result = await load_ir_full_text(item, record, max_chars=1_000_000)

    assert result.from_pdf is False
    assert result.text == "fallback summary"


async def test_load_ir_full_text_truncates_when_over_max_chars() -> None:
    """max_chars を超えると切り詰められ、truncated=True になる."""
    item, record = _make_ir_document(pdf_path=None)
    item.summary = "x" * 100

    result = await load_ir_full_text(item, record, max_chars=10)

    assert result.truncated is True
    assert len(result.text) == 10  # noqa: PLR2004
