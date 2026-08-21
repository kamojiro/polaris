"""論文の本文全文をロードする(015-paper-qa-chat).

ベクトル検索(Chunk/Embedding)を経由せず、`get_paper_full_text` ツールから
呼ばれてそのままエージェントのコンテキストに渡す用途。`PaperRecord.pdf_path`
から都度 pypdf で再抽出することで、既存の Ingest 済みデータに対する
スキーマ変更・再Ingestを一切不要にしている。PDFが無い/読めない場合のみ、
既に永続化済みのチャンクを連結してフォールバックする(劣化するが動作は続行する)。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from polaris.adapters.pdf.extractor import PdfExtractionError, extract_pdf_text

if TYPE_CHECKING:
    from polaris.db.repository import PaperRepository
    from polaris.domain.entities import Item, PaperRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperFullText:
    """`load_full_text` の戻り値."""

    text: str
    truncated: bool
    from_pdf: bool  # False の場合、チャンク連結によるフォールバック経由


def _load_from_chunks(repo: PaperRepository, item_id: str) -> str:
    """チャンクを order 順に連結して本文の代わりにする(PDFが使えない場合のフォールバック).

    チャンク分割時のオーバーラップ分(chunk_overlap_chars)が単純連結では重複するが、
    PDFが手元に無い場合の劣化フォールバックとして許容する。
    """
    chunks = repo.list_chunks(item_id)
    return "\n\n".join(chunk.text for chunk in chunks)


async def load_full_text(
    item: Item,
    record: PaperRecord,
    *,
    repo: PaperRepository,
    max_chars: int,
) -> PaperFullText:
    """指定論文の本文全文をロードする(pdf_path から再抽出、失敗時はチャンク連結にフォールバック)."""
    text = ""
    from_pdf = False

    if record.pdf_path is not None:
        pdf_path = Path(record.pdf_path)
        try:
            text = await asyncio.to_thread(extract_pdf_text, pdf_path)
            from_pdf = bool(text.strip())
        except PdfExtractionError:
            logger.warning("PDFからの全文再抽出に失敗、チャンク連結にフォールバックします: %s", item.id, exc_info=True)

    if not text.strip():
        text = await asyncio.to_thread(_load_from_chunks, repo, item.id)
        from_pdf = False

    if not text.strip():
        # チャンクすら無い場合(要約生成前など)の最終フォールバック。
        text = item.summary

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return PaperFullText(text=text, truncated=truncated, from_pdf=from_pdf)
