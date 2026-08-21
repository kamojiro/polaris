"""汎用 PDF ダウンロード(fetch_pdf)の純ロジックテスト."""

from pathlib import Path

import httpx
import pytest
import respx

from polaris.adapters.pdf.downloader import PdfDownloadError, fetch_pdf

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_PDF_BYTES = (_FIXTURE_DIR / "attention.pdf").read_bytes()
_URL = "https://example.com/papers/some-paper.pdf"


async def test_fetch_pdf_succeeds_with_pdf_content_type() -> None:
    """Content-Type が application/pdf のレスポンスは PDF としてそのまま返る."""
    with respx.mock:
        respx.get(_URL).mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/pdf"}),
        )
        async with httpx.AsyncClient() as client:
            content = await fetch_pdf(_URL, client=client, max_bytes=10_000_000)

    assert content == _PDF_BYTES


async def test_fetch_pdf_succeeds_via_magic_bytes_when_content_type_is_wrong() -> None:
    """Content-Type が雑でも、先頭が %PDF ならマジックバイトで PDF と判定して受け入れる."""
    with respx.mock:
        respx.get(_URL).mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/octet-stream"}),
        )
        async with httpx.AsyncClient() as client:
            content = await fetch_pdf(_URL, client=client, max_bytes=10_000_000)

    assert content == _PDF_BYTES


async def test_fetch_pdf_rejects_non_pdf_content() -> None:
    """PDFではないコンテンツ(HTMLページ等)は PdfDownloadError になる."""
    with respx.mock:
        respx.get(_URL).mock(
            return_value=httpx.Response(200, content=b"<html>not a pdf</html>", headers={"content-type": "text/html"}),
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(PdfDownloadError):
                await fetch_pdf(_URL, client=client, max_bytes=10_000_000)


async def test_fetch_pdf_raises_on_http_error() -> None:
    """HTTPエラー(404等)は PdfDownloadError になる."""
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            with pytest.raises(PdfDownloadError):
                await fetch_pdf(_URL, client=client, max_bytes=10_000_000)


async def test_fetch_pdf_rejects_oversized_content() -> None:
    """サイズが上限を超える場合は PdfDownloadError になる."""
    with respx.mock:
        respx.get(_URL).mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/pdf"}),
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(PdfDownloadError):
                await fetch_pdf(_URL, client=client, max_bytes=10)
