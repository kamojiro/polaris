"""ArXiv URL から論文を取り込む full ingest パイプライン(002-papers-ingest-full).

メタデータ取得 → PDF取得・本文抽出 → Structure(要約/venue生成) → チャンク分割
→ Embedding生成 → 永続化、の順で進める。PDF取得・本文抽出に失敗しても abstract
のみで続行し、Item/PaperRecordの登録自体は失わない(spec のエラーハンドリング
方針)。arxiv_id で重複を防ぎ、メタデータのみ登録済み(チャンク未生成)の場合は
そこから再開する(部分的成功からの冪等な再実行)。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import httpx

from polaris.adapters.arxiv.client import fetch_arxiv_metadata, fetch_arxiv_pdf
from polaris.adapters.arxiv.parser import extract_arxiv_id
from polaris.adapters.pdf.extractor import PdfExtractionError, extract_pdf_text
from polaris.domain.entities import Chunk, EmbeddingRecord, Item, ItemType, PaperRecord
from polaris.services.chunking import ChunkDraft, split_into_chunks

if TYPE_CHECKING:
    from polaris.adapters.arxiv.parser import ArxivMetadata
    from polaris.adapters.embeddings import EmbeddingModel
    from polaris.agent.structure_paper import PaperStructurer
    from polaris.db.repository import PaperRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)


class InvalidPaperUrlError(Exception):
    """arXiv の URL / ID として解釈できなかった場合の例外."""


class IngestResult(NamedTuple):
    """`ingest_paper_from_url` の戻り値."""

    item: Item
    record: PaperRecord
    chunks: list[Chunk]
    created: bool


def _build_metadata_records(metadata: ArxivMetadata) -> tuple[Item, PaperRecord]:
    """ArXiv メタデータから Item / PaperRecord を組み立てる(まだ保存しない)."""
    now = datetime.now(UTC)
    record = PaperRecord(
        id=uuid.uuid4().hex,
        item_id="",  # 直後に確定させる
        authors=metadata.authors,
        year=metadata.year,
        doi=metadata.doi,
        arxiv_id=metadata.arxiv_id,
        abstract=metadata.abstract,
        # ユーザーが貼った生の URL(/pdf/ やバージョン付き)ではなく、
        # 正規化した arxiv_id から組み立てた /abs/ ページに揃える。
        source_url=f"https://arxiv.org/abs/{metadata.arxiv_id}",
        ingested_at=now,
    )
    item = Item(
        id=uuid.uuid4().hex,
        item_type=ItemType.paper,
        title=metadata.title,
        summary=metadata.abstract,  # Structure ステップで生成した要約に後で置き換わる暫定値
        created_at=now,
        source_ref=f"paper:{record.id}",
    )
    record.item_id = item.id
    return item, record


async def _fetch_body_text(
    record: PaperRecord,
    arxiv_id: str,
    *,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> tuple[str, bool]:
    """PDF をダウンロード・保存して本文を抽出する.

    ダウンロードまたは抽出に失敗した場合は warning ログを出し、abstract を
    本文の代わりに返す。戻り値の bool は PDF 本文の抽出に成功したかどうかで、
    False の場合は呼び出し側が abstract をチャンク分割せず単一チャンクとして扱う。
    成功時は `record.pdf_path` を更新する(呼び出し側で永続化する)。
    """
    pdf_dir = Path(settings.ingest.pdf_dir)
    await asyncio.to_thread(pdf_dir.mkdir, parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{arxiv_id}.pdf"

    try:
        pdf_bytes = await fetch_arxiv_pdf(arxiv_id, client=http_client)
        pdf_path.write_bytes(pdf_bytes)
        text = extract_pdf_text(pdf_path)
    except httpx.HTTPError, PdfExtractionError:
        logger.warning("PDF取得/抽出に失敗したため abstract のみで続行します: %s", arxiv_id, exc_info=True)
        return record.abstract, False

    if not text.strip():
        logger.warning("PDF本文が空だったため abstract のみで続行します: %s", arxiv_id)
        return record.abstract, False

    record.pdf_path = str(pdf_path)
    return text, True


async def ingest_paper_from_url(
    url: str,
    *,
    repo: PaperRepository,
    http_client: httpx.AsyncClient,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
    settings: Settings,
) -> IngestResult:
    """ArXiv URL から論文を取り込む.

    既にチャンクまで永続化済みであれば取得済みとして返す(冪等)。メタデータのみ
    登録済み(チャンク未生成)であれば、そこから続きを実行する。
    """
    arxiv_id = extract_arxiv_id(url)
    if arxiv_id is None:
        raise InvalidPaperUrlError(url)

    logger.info("Ingest開始: arxiv_id=%s", arxiv_id)

    existing = repo.find_by_arxiv_id(arxiv_id)
    if existing is not None:
        item, record = existing
        chunks = repo.list_chunks(item.id)
        if chunks:
            logger.info("既にIngest済み(チャンク数=%d)なのでスキップ: arxiv_id=%s", len(chunks), arxiv_id)
            return IngestResult(item, record, chunks, created=False)
        logger.info("メタデータのみ登録済み、続きから再開: arxiv_id=%s", arxiv_id)

    # comment(venue推定のヒント)取得のため、既存レコードの再開時も含めて必ず取得する。
    metadata = await fetch_arxiv_metadata(arxiv_id, client=http_client)
    logger.info("メタデータ取得完了: title=%s", metadata.title)

    if existing is None:
        item, record = _build_metadata_records(metadata)
        repo.save_paper(item, record)
    else:
        item, record = existing

    body_text, from_pdf = await _fetch_body_text(record, arxiv_id, http_client=http_client, settings=settings)
    logger.info(
        "本文取得%s: %d文字",
        "成功(PDF)" if from_pdf else "失敗のため abstract で続行",
        len(body_text),
    )

    structured = await structurer.structure(title=item.title, abstract=record.abstract, comment=metadata.comment)
    item.summary = structured.summary
    record.venue = structured.venue
    repo.update_item(item)
    repo.update_paper_record(record)
    logger.info("Structure完了: venue=%s", structured.venue)

    if from_pdf:
        chunk_drafts = split_into_chunks(
            body_text,
            chunk_chars=settings.ingest.chunk_chars,
            overlap_chars=settings.ingest.chunk_overlap_chars,
        )
    else:
        # PDF本文が使えない場合は abstract をチャンク分割せず単一チャンクとして扱う。
        chunk_drafts = [ChunkDraft(section=None, order=0, text=body_text)]
    chunks = [
        Chunk(id=uuid.uuid4().hex, item_id=item.id, section=draft.section, order=draft.order, text=draft.text)
        for draft in chunk_drafts
    ]
    repo.save_chunks(chunks)
    logger.info("チャンク分割完了: %d チャンク", len(chunks))

    logger.info("Embedding開始: %d チャンク (model=%s)", len(chunks), embedder.model_id)
    vectors = await embedder.embed_batch([chunk.text for chunk in chunks])
    embedding_records = [
        EmbeddingRecord(chunk_id=chunk.id, vector=vector, model=embedder.model_id)
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    repo.save_embeddings(embedding_records)
    logger.info("Ingest完了: arxiv_id=%s, %d チャンク", arxiv_id, len(chunks))

    return IngestResult(item, record, chunks, created=True)
