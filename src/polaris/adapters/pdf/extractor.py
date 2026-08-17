"""pypdf による PDF 本文テキスト抽出."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pypdf import PdfReader

if TYPE_CHECKING:
    from pathlib import Path


class PdfExtractionError(Exception):
    """PDF の読み込み・テキスト抽出に失敗した場合の例外.

    呼び出し側(ingest_paper)でキャッチし、abstract のみで続行するフォールバックに使う。
    """


def extract_pdf_text(pdf_path: Path) -> str:
    """PDF の全ページからテキストを抽出して結合する.

    スキャンPDF等でテキストが取れないページは空文字のまま無視する。
    ファイル自体が壊れている等で読み込みに失敗した場合は PdfExtractionError を送出する。
    """
    try:
        reader = PdfReader(pdf_path)
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise PdfExtractionError(str(pdf_path)) from exc
    return "\n".join(pages_text).strip()
