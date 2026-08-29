"""IR文書の本文全文をロードする(013-ir-analysis-domain).

`services/paper_full_text.py`と同じ考え方: ベクトル検索(Chunk/Embedding)を経由せず、
`get_ir_full_text` ツールから呼ばれてそのままエージェントのコンテキストに渡す用途。
`IrRecord.pdf_path`から都度pypdfで再抽出する。IR文書はv1でChunkを作らないため、
チャンク連結フォールバックは無く、再抽出に失敗した場合は`Item.summary`にフォールバックする。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from polaris.adapters.pdf.extractor import PdfExtractionError, extract_pdf_text

if TYPE_CHECKING:
    from polaris.domain.entities import IrRecord, Item

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IrFullText:
    """`load_ir_full_text` の戻り値."""

    text: str
    truncated: bool
    from_pdf: bool  # False の場合、Item.summary によるフォールバック経由


async def load_ir_full_text(item: Item, record: IrRecord, *, max_chars: int) -> IrFullText:
    """指定IR文書の本文全文をロードする(pdf_path から再抽出、失敗時は summary にフォールバック)."""
    text = ""
    from_pdf = False

    if record.pdf_path is not None:
        pdf_path = Path(record.pdf_path)
        try:
            text = await asyncio.to_thread(extract_pdf_text, pdf_path)
            from_pdf = bool(text.strip())
        except PdfExtractionError:
            logger.warning("PDFからの全文再抽出に失敗、summaryにフォールバックします: %s", item.id, exc_info=True)

    if not text.strip():
        # PDFが無い/読めない場合の最終フォールバック(v1はChunkが無いため他に手段が無い)。
        text = item.summary
        from_pdf = False

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return IrFullText(text=text, truncated=truncated, from_pdf=from_pdf)
