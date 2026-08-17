"""extract_pdf_text の純ロジックテスト(小さな実PDFフィクスチャを使用)."""

from pathlib import Path

import pytest

from polaris.adapters.pdf.extractor import PdfExtractionError, extract_pdf_text

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_extract_pdf_text_reads_real_paper() -> None:
    """実際のarXiv論文PDFから本文テキストを抽出できる."""
    text = extract_pdf_text(_FIXTURE_DIR / "attention.pdf")

    assert "Attention Is All You Need" in text
    assert "Introduction" in text
    assert len(text) > 1000  # noqa: PLR2004


def test_extract_pdf_text_raises_on_corrupt_file() -> None:
    """PDFとして読めないファイルは PdfExtractionError になる."""
    with pytest.raises(PdfExtractionError):
        extract_pdf_text(_FIXTURE_DIR / "corrupt.pdf")
