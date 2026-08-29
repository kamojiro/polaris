"""IR文書(Item + IrRecord)を取り込む Ingest パイプライン(013-ir-analysis-domain).

`services/ingest_paper.py`の`_ingest_from_pdf`(URL/アップロード経路)と同じ形を
踏襲する: PDF取得 → 本文抽出 → メタデータ抽出(LLM1回でsummaryも同時生成)→ 永続化。
論文ドメインと異なりChunk/Embeddingは作らない(spec「データモデル」参照、全文は
`services/ir_full_text.py`が都度PDFから再抽出する)。

doc_id(EDINETの書類管理番号)で重複を防ぐ(`arxiv_id`と同じ役割の自然キー)。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from polaris.adapters.edinet.client import fetch_edinet_document_pdf
from polaris.adapters.pdf.extractor import PdfExtractionError, extract_pdf_text
from polaris.domain.entities import IrRecord, Item, ItemType
from polaris.services.progress import set_progress

if TYPE_CHECKING:
    import httpx

    from polaris.agent.extract_ir_metadata import ExtractedIrDocument, IrMetadataExtractor
    from polaris.db.ir_repository import IrRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

__all__ = ["IrIngestResult", "ingest_ir_document"]


class IrIngestResult(NamedTuple):
    """`ingest_ir_document` の戻り値."""

    item: Item
    record: IrRecord
    created: bool


def _parse_date(value: str | None) -> date | None:
    """LLMが返したISO 8601形式の日付文字列をdateに変換する(パースできなければNone)."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        logger.warning("日付の解析に失敗したため null 扱いにします: %s", value)
        return None


def _build_records(
    doc_id: str,
    extracted: ExtractedIrDocument,
    *,
    pdf_path: Path,
) -> tuple[Item, IrRecord]:
    """メタデータ抽出結果から Item / IrRecord を組み立てる(まだ保存しない)."""
    now = datetime.now(UTC)
    submit_datetime = _parse_date(extracted.submit_datetime)
    record = IrRecord(
        id=uuid.uuid4().hex,
        item_id="",  # 直後に確定させる
        doc_id=doc_id,
        filer_name=extracted.filer_name,
        edinet_code=extracted.edinet_code,
        doc_type_code=extracted.doc_type_code,
        period_start=_parse_date(extracted.period_start),
        period_end=_parse_date(extracted.period_end),
        # submit_datetime はEDINETの書類一覧API(v1では呼ばない、spec参照)からしか
        # 正確には取れない。表紙のテキストからLLMが読み取れればそれを使い、
        # 読み取れなければ Ingest 時刻を代わりに入れる(実際の提出日時とはズレうる)。
        submit_datetime=datetime.combine(submit_datetime, datetime.min.time(), tzinfo=UTC)
        if submit_datetime is not None
        else now,
        pdf_path=str(pdf_path),
        ingested_at=now,
    )
    item = Item(
        id=uuid.uuid4().hex,
        item_type=ItemType.ir_document,
        title=f"{extracted.filer_name} {extracted.doc_type_code or ''}".strip(),
        summary=extracted.summary,
        created_at=now,
        source_ref=f"ir_document:{record.id}",
    )
    record.item_id = item.id
    return item, record


async def ingest_ir_document(
    doc_id: str,
    *,
    repo: IrRepository,
    http_client: httpx.AsyncClient,
    extractor: IrMetadataExtractor,
    settings: Settings,
) -> IrIngestResult:
    """EDINETのdoc_id(書類管理番号)からIR文書を取り込む.

    既に取り込み済みであれば再取得せず既存レコードを返す(002/015と同じ冪等性の考え方、
    spec「処理フロー」参照)。
    """
    existing = repo.find_by_doc_id(doc_id)
    if existing is not None:
        logger.info("既にIngest済みなのでスキップ: doc_id=%s", doc_id)
        item, record = existing
        return IrIngestResult(item, record, created=False)

    logger.info("Ingest開始(EDINET): doc_id=%s", doc_id)
    ingest_start = time.perf_counter()

    pdf_dir = Path(settings.ir.pdf_dir)
    await asyncio.to_thread(pdf_dir.mkdir, parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{doc_id}.pdf"

    set_progress("stage", "EDINETから書類を取得中…")
    try:
        pdf_bytes = await fetch_edinet_document_pdf(
            doc_id,
            client=http_client,
            base_url=settings.ir.edinet_base_url,
            api_key=settings.ir.edinet_api_key,
        )
        await asyncio.to_thread(pdf_path.write_bytes, pdf_bytes)

        set_progress("stage", "本文を抽出中…")
        text = await asyncio.to_thread(extract_pdf_text, pdf_path)
        if not text.strip():
            raise PdfExtractionError(str(pdf_path))
        logger.info("本文抽出完了: %d文字", len(text))

        set_progress("stage", "メタデータを抽出中…")
        extracted = await extractor.extract(body_head=text[: settings.ir.metadata_head_chars])
        logger.info("メタデータ抽出完了: filer_name=%s", extracted.filer_name)
    finally:
        set_progress("stage", None)

    item, record = _build_records(doc_id, extracted, pdf_path=pdf_path)
    repo.save_ir_document(item, record)

    logger.info(
        "Ingest完了(%.2fs): doc_id=%s, filer_name=%s",
        time.perf_counter() - ingest_start,
        doc_id,
        record.filer_name,
    )
    return IrIngestResult(item, record, created=True)
