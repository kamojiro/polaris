"""adapters/edinet/client.py のテスト(013-ir-analysis-domain)."""

from pathlib import Path

import httpx
import pytest
import respx

from polaris.adapters.edinet.client import EdinetClientError, fetch_edinet_document_pdf

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_PDF_BYTES = (_FIXTURE_DIR / "attention.pdf").read_bytes()
_BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2"
_DOC_ID = "S100XXXX"


async def test_fetch_edinet_document_pdf_returns_pdf_bytes() -> None:
    """type=2 のPDFレスポンスをそのままバイト列として返す."""
    with respx.mock:
        route = respx.get(f"{_BASE_URL}/documents/{_DOC_ID}").mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/pdf"}),
        )
        async with httpx.AsyncClient() as client:
            content = await fetch_edinet_document_pdf(_DOC_ID, client=client, base_url=_BASE_URL, api_key="test-key")

    assert content == _PDF_BYTES
    assert route.calls.last.request.url.params["type"] == "2"
    assert route.calls.last.request.url.params["Subscription-Key"] == "test-key"


async def test_fetch_edinet_document_pdf_raises_on_http_error() -> None:
    """HTTPエラー(404等)は EdinetClientError になる."""
    with respx.mock:
        respx.get(f"{_BASE_URL}/documents/{_DOC_ID}").mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            with pytest.raises(EdinetClientError):
                await fetch_edinet_document_pdf(_DOC_ID, client=client, base_url=_BASE_URL, api_key="test-key")


async def test_fetch_edinet_document_pdf_raises_on_server_error() -> None:
    """5xxエラーも EdinetClientError になる."""
    with respx.mock:
        respx.get(f"{_BASE_URL}/documents/{_DOC_ID}").mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            with pytest.raises(EdinetClientError):
                await fetch_edinet_document_pdf(_DOC_ID, client=client, base_url=_BASE_URL, api_key="test-key")
