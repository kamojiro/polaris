"""汎用 PDF ダウンロード(014-paper-url-pdf-ingest の URL 直リンク入力用).

arXiv 経由(`adapters/arxiv/client.py:fetch_arxiv_pdf`)とは別に、任意の URL から
PDF をダウンロードするための薄いアダプタ。arXiv 側は URL 組み立てが arXiv 固有
(`_ARXIV_PDF_URL.format(arxiv_id=...)`)なのでこちらとは統合しない。
"""

from __future__ import annotations

import httpx

_PDF_TIMEOUT_SECONDS = 60.0
_PDF_MAGIC_BYTES = b"%PDF"


class PdfDownloadError(Exception):
    """PDF のダウンロード、または取得したデータが PDF として妥当でない場合の例外."""


async def fetch_pdf(url: str, *, client: httpx.AsyncClient, max_bytes: int) -> bytes:
    """任意の URL から PDF をダウンロードする.

    Content-Type ヘッダーは雑に "application/octet-stream" 等を返すサーバーも
    あるため過信せず、先頭のマジックバイト(`%PDF`)でも実体が PDF かを確認する。
    サイズ上限は Ingest パイプラインが際限なく巨大なファイルを処理しないための
    ガード(`settings.ingest.max_pdf_bytes`)。
    """
    try:
        response = await client.get(url, timeout=_PDF_TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"PDFのダウンロードに失敗しました: {url}"
        raise PdfDownloadError(msg) from exc

    content = response.content
    if len(content) > max_bytes:
        msg = f"PDFのサイズが上限({max_bytes}バイト)を超えています: {url}"
        raise PdfDownloadError(msg)

    content_type = response.headers.get("content-type", "")
    looks_like_pdf = "pdf" in content_type.lower() or content.startswith(_PDF_MAGIC_BYTES)
    if not looks_like_pdf:
        msg = f"PDFではないコンテンツが返されました(content-type={content_type}): {url}"
        raise PdfDownloadError(msg)

    return content
