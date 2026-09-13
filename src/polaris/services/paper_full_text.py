"""論文の本文全文をロードする(015-paper-qa-chat).

ベクトル検索(Chunk/Embedding)を経由せず、`get_paper_full_text` ツールから
呼ばれてそのままエージェントのコンテキストに渡す用途。`PaperRecord.pdf_path`
から都度 pypdf で再抽出するのが基本経路。PDFが無い/読めない場合は、
Ingest時に抽出成功した全文を保存しておいた`record.text_path`を読む
(改訂 2026-09-13、`specs/015-paper-qa-chat/spec.draft.md`参照)。

**旧方式からの変更点**: 以前はチャンク(`Chunk`テーブル)を order 順に連結する
フォールバックだったが、チャンクは元々オーバーラップ付きで分割されている
(embedding用の切り方)ため、単純連結すると境界部分が重複する欠陥があった。
`text_path`が未設定(このフィールド追加より前にIngestした論文)の場合は
チャンク連結には戻さず、そのまま最終フォールバック(`item.summary`)に進む。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from polaris.adapters.pdf.extractor import PdfExtractionError, extract_pdf_text

if TYPE_CHECKING:
    from polaris.domain.entities import Item, PaperRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperFullText:
    """`load_full_text` の戻り値."""

    text: str
    truncated: bool
    from_pdf: bool  # False の場合、永続化済み全文ファイル(または最終フォールバック)経由


def _load_from_text_path(text_path: str) -> str:
    """Ingest時に保存した全文ファイルを読む(PDF再抽出が使えない場合のフォールバック)."""
    try:
        return Path(text_path).read_text(encoding="utf-8")
    except OSError:
        logger.warning("永続化済み全文ファイルの読み込みに失敗しました: %s", text_path, exc_info=True)
        return ""


async def load_full_text(
    item: Item,
    record: PaperRecord,
    *,
    max_chars: int,
) -> PaperFullText:
    """指定論文の本文全文をロードする(pdf_path から再抽出、失敗時は永続化済み全文ファイルにフォールバック)."""
    text = ""
    from_pdf = False

    if record.pdf_path is not None:
        pdf_path = Path(record.pdf_path)
        try:
            text = await asyncio.to_thread(extract_pdf_text, pdf_path)
            from_pdf = bool(text.strip())
        except PdfExtractionError:
            logger.warning(
                "PDFからの全文再抽出に失敗、永続化済み全文ファイルにフォールバックします: %s", item.id, exc_info=True
            )

    if not text.strip() and record.text_path is not None:
        text = await asyncio.to_thread(_load_from_text_path, record.text_path)
        from_pdf = False

    if not text.strip():
        # 全文ファイルも無い場合(text_path追加より前にIngestした論文等)の最終フォールバック。
        text = item.summary

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return PaperFullText(text=text, truncated=truncated, from_pdf=from_pdf)
