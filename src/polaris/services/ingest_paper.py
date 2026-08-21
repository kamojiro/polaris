"""論文を取り込む Ingest パイプライン(002-papers-ingest-full / 014-paper-url-pdf-ingest).

入力は `paper_source.resolve_source()` で arXiv / URL直リンク / アップロード済み
ローカルPDFの3経路に振り分けられる(002 spec が「将来拡張できる形で用意した」と
していた `InputKind` は実際にはコードに存在せず、014着手時にこのモジュールとして
新設した)。

arXiv経路: メタデータ取得(arXiv API) → PDF取得・本文抽出 → Structure(要約/venue生成)
→ チャンク分割 → Embedding生成 → 永続化。PDF取得・本文抽出に失敗しても abstract
のみで続行し、Item/PaperRecordの登録自体は失わない(spec のエラーハンドリング方針)。
arxiv_id で重複を防ぎ、メタデータのみ登録済み(チャンク未生成)の場合はそこから
再開する(部分的成功からの冪等な再実行)。

URL/アップロード経路: title/abstract の供給元(arXiv API相当)が無いため、
PDF取得 → 本文抽出 → メタデータ抽出(LLM 1回でsummaryも同時生成)→ 永続化 →
チャンク分割 → Embedding生成、の順になる。本文抽出に失敗した場合はabstract相当の
フォールバックが無い(Item.titleを埋める手段が無い)ため、Ingest全体を失敗させる。
source_url で重複を防ぐ(arxiv_idを持たないため)。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import httpx
from sqlalchemy.exc import IntegrityError

from polaris.adapters.arxiv.client import fetch_arxiv_metadata, fetch_arxiv_pdf
from polaris.adapters.pdf.downloader import fetch_pdf
from polaris.adapters.pdf.extractor import PdfExtractionError, extract_pdf_text
from polaris.domain.entities import Chunk, EmbeddingRecord, Item, ItemType, PaperRecord
from polaris.services.chunking import ChunkDraft, split_into_chunks
from polaris.services.paper_source import (
    ArxivSource,
    InvalidPaperUrlError,
    UrlSource,
    resolve_source,
)
from polaris.services.progress import set_progress

if TYPE_CHECKING:
    from polaris.adapters.arxiv.parser import ArxivMetadata
    from polaris.adapters.embeddings import EmbeddingModel
    from polaris.agent.extract_metadata import ExtractedPaper, PaperMetadataExtractor
    from polaris.agent.structure_paper import PaperStructurer, StructuredPaper
    from polaris.db.repository import PaperRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

__all__ = ["IngestResult", "InvalidPaperUrlError", "ingest_paper_from_url"]


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


def _build_pdf_records(extracted: ExtractedPaper, *, source_url: str, pdf_path: Path) -> tuple[Item, PaperRecord]:
    """メタデータ抽出(URL/アップロード経路)結果から Item / PaperRecord を組み立てる(まだ保存しない)."""
    now = datetime.now(UTC)
    record = PaperRecord(
        id=uuid.uuid4().hex,
        item_id="",  # 直後に確定させる
        authors=extracted.authors,
        year=extracted.year,
        venue=extracted.venue,
        doi=extracted.doi,
        arxiv_id=None,
        abstract=extracted.abstract,
        source_url=source_url,
        pdf_path=str(pdf_path),
        ingested_at=now,
    )
    item = Item(
        id=uuid.uuid4().hex,
        item_type=ItemType.paper,
        title=extracted.title or "(タイトル不明)",
        summary=extracted.summary,
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
        await asyncio.to_thread(pdf_path.write_bytes, pdf_bytes)
        text = await asyncio.to_thread(extract_pdf_text, pdf_path)
    except (httpx.HTTPError, PdfExtractionError):
        logger.warning("PDF取得/抽出に失敗したため abstract のみで続行します: %s", arxiv_id, exc_info=True)
        return record.abstract, False

    if not text.strip():
        logger.warning("PDF本文が空だったため abstract のみで続行します: %s", arxiv_id)
        return record.abstract, False

    record.pdf_path = str(pdf_path)
    return text, True


async def _run_structure(
    structurer: PaperStructurer,
    *,
    title: str,
    abstract: str,
    comment: str | None,
) -> StructuredPaper:
    """Structure(要約/venue生成)を実行し、進捗と所要時間を記録する."""
    set_progress("structure", "要約を生成中…")
    start = time.perf_counter()
    structured = await structurer.structure(title=title, abstract=abstract, comment=comment)
    logger.info("Structure完了(%.2fs): venue=%s", time.perf_counter() - start, structured.venue)
    set_progress("structure", "要約生成完了")
    return structured


async def _chunk_and_embed(
    body_text: str,
    *,
    from_pdf: bool,
    item: Item,
    embedder: EmbeddingModel,
    repo: PaperRepository,
    settings: Settings,
) -> list[Chunk]:
    """本文をチャンク分割し、Embeddingを生成してどちらも永続化する."""
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
    set_progress("embedding", f"Embedding生成中: 0/{len(chunks)} チャンク完了")
    vectors = await embedder.embed_batch([chunk.text for chunk in chunks])
    embedding_records = [
        EmbeddingRecord(chunk_id=chunk.id, vector=vector, model=embedder.model_id)
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    repo.save_embeddings(embedding_records)
    return chunks


def _resolve_save_conflict(
    repo: PaperRepository,
    arxiv_id: str,
    error: IntegrityError,
) -> tuple[Item, PaperRecord, list[Chunk]]:
    """save_paper が UNIQUE 制約違反で失敗した際、先に確定した既存レコードを取得する.

    同じ arxiv_id を同時に取り込もうとした別リクエストが先に確定した(競合)。
    find_by_arxiv_id が「無い」と判定してから保存するまではアトミックではないため
    起こりうる。自分で組み立てたレコードは使わず、先に確定した方へ切り替える。
    """
    logger.info("arxiv_id=%s は同時保存により競合、既存レコードへ切り替え", arxiv_id)
    winner = repo.find_by_arxiv_id(arxiv_id)
    if winner is None:
        raise error
    item, record = winner
    return item, record, repo.list_chunks(item.id)


async def _ingest_arxiv(
    arxiv_id: str,
    *,
    repo: PaperRepository,
    http_client: httpx.AsyncClient,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
    settings: Settings,
) -> IngestResult:
    """ArXiv の arxiv_id から論文を取り込む(002-papers-ingest-full 本体、挙動は変更していない).

    既にチャンクまで永続化済みであれば取得済みとして返す(冪等)。メタデータのみ
    登録済み(チャンク未生成)であれば、そこから続きを実行する。
    """
    logger.info("Ingest開始(arXiv): arxiv_id=%s", arxiv_id)
    ingest_start = time.perf_counter()

    existing = repo.find_by_arxiv_id(arxiv_id)
    if existing is not None:
        item, record = existing
        chunks = repo.list_chunks(item.id)
        if chunks:
            logger.info("既にIngest済み(チャンク数=%d)なのでスキップ: arxiv_id=%s", len(chunks), arxiv_id)
            return IngestResult(item, record, chunks, created=False)
        logger.info("メタデータのみ登録済み、続きから再開: arxiv_id=%s", arxiv_id)

    # comment(venue推定のヒント)取得のため、既存レコードの再開時も含めて必ず取得する。
    set_progress("stage", "メタデータを取得中…")
    metadata = await fetch_arxiv_metadata(arxiv_id, client=http_client)
    logger.info("メタデータ取得完了: title=%s", metadata.title)

    if existing is None:
        item, record = _build_metadata_records(metadata)
        try:
            repo.save_paper(item, record)
        except IntegrityError as exc:
            item, record, winner_chunks = _resolve_save_conflict(repo, arxiv_id, exc)
            if winner_chunks:
                return IngestResult(item, record, winner_chunks, created=False)
    else:
        item, record = existing

    # 要約生成(Structure)はmetadataのtitle/abstract/commentだけで完結し、PDF本文や
    # チャンク・Embeddingの結果には依存しない。ここでバックグラウンドタスクとして
    # 起動しておき、PDF取得・チャンク分割・Embedding生成の間ずっと並行させ、
    # 本当に必要になる最後(保存直前)まで結果を待たない。進捗表示も
    # "stage"(PDF取得)と"structure"(要約)を別行にして、両方同時に見えるようにする。
    set_progress("stage", "PDF取得中…")
    structure_task = asyncio.create_task(
        _run_structure(structurer, title=item.title, abstract=record.abstract, comment=metadata.comment),
    )
    try:
        body_text, from_pdf = await _fetch_body_text(record, arxiv_id, http_client=http_client, settings=settings)
        set_progress("stage", None)
        logger.info(
            "本文取得%s: %d文字",
            "成功(PDF)" if from_pdf else "失敗のため abstract で続行",
            len(body_text),
        )
        chunks = await _chunk_and_embed(
            body_text,
            from_pdf=from_pdf,
            item=item,
            embedder=embedder,
            repo=repo,
            settings=settings,
        )
        structured = await structure_task
    finally:
        if not structure_task.done():
            structure_task.cancel()
        set_progress("stage", None)
        set_progress("structure", None)

    item.summary = structured.summary
    record.venue = structured.venue
    repo.update_item(item)
    repo.update_paper_record(record)

    logger.info(
        "Ingest完了(%.2fs): arxiv_id=%s, %d チャンク",
        time.perf_counter() - ingest_start,
        arxiv_id,
        len(chunks),
    )

    return IngestResult(item, record, chunks, created=True)


async def _ingest_from_pdf(
    pdf_bytes: bytes,
    *,
    source_url: str,
    embedder: EmbeddingModel,
    extractor: PaperMetadataExtractor,
    repo: PaperRepository,
    settings: Settings,
) -> IngestResult:
    """URL直リンク/アップロード共通の取り込み本体(PDFバイト列から先).

    arXiv経路と異なり title/abstract の供給元が無いため、本文抽出→
    メタデータ抽出(LLM 1回でsummaryも同時生成)→保存の順で進む。
    本文抽出に失敗した場合、arXiv経路のようなabstractフォールバックが
    存在しない(Item.titleを埋める手段が無い)ため、ここでは例外を送出して
    Ingest全体を失敗させる。

    重複判定は source_url で行うが、DB側に unique 制約は付けていない
    (既存 data/polaris.db のスキーマ変更を避けるため)ため、arXiv経路の
    ような IntegrityError ベースの競合解決は行わない。個人用ツールで
    同時実行は基本無いという前提の割り切り(YAGNI)。
    """
    existing = repo.find_by_source_url(source_url)
    if existing is not None:
        item, record = existing
        chunks = repo.list_chunks(item.id)
        if chunks:
            logger.info("既にIngest済み(チャンク数=%d)なのでスキップ: source_url=%s", len(chunks), source_url)
            return IngestResult(item, record, chunks, created=False)

    ingest_start = time.perf_counter()
    pdf_dir = Path(settings.ingest.pdf_dir)
    await asyncio.to_thread(pdf_dir.mkdir, parents=True, exist_ok=True)
    # arXiv経路の "{arxiv_id}.pdf" と衝突しないよう、内容のハッシュをファイル名にする。
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_path = pdf_dir / f"{digest[:16]}.pdf"
    await asyncio.to_thread(pdf_path.write_bytes, pdf_bytes)

    try:
        set_progress("stage", "本文を抽出中…")
        text = await asyncio.to_thread(extract_pdf_text, pdf_path)
        if not text.strip():
            raise PdfExtractionError(str(pdf_path))
        logger.info("本文抽出完了: %d文字", len(text))

        set_progress("stage", "メタデータを抽出中…")
        extracted = await extractor.extract(body_head=text[: settings.ingest.metadata_head_chars])
        logger.info("メタデータ抽出完了: title=%s", extracted.title)
    finally:
        set_progress("stage", None)

    item, record = _build_pdf_records(extracted, source_url=source_url, pdf_path=pdf_path)
    repo.save_paper(item, record)

    chunks = await _chunk_and_embed(
        text,
        from_pdf=True,
        item=item,
        embedder=embedder,
        repo=repo,
        settings=settings,
    )

    logger.info(
        "Ingest完了(%.2fs): source_url=%s, %d チャンク",
        time.perf_counter() - ingest_start,
        source_url,
        len(chunks),
    )
    return IngestResult(item, record, chunks, created=True)


async def ingest_paper_from_url(
    text: str,
    *,
    repo: PaperRepository,
    http_client: httpx.AsyncClient,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
    extractor: PaperMetadataExtractor,
    settings: Settings,
) -> IngestResult:
    """入力文字列(arXiv URL/ID、PDF直リンクURL、または upload://<id>)から論文を取り込む."""
    source = resolve_source(text)

    if isinstance(source, ArxivSource):
        return await _ingest_arxiv(
            source.arxiv_id,
            repo=repo,
            http_client=http_client,
            embedder=embedder,
            structurer=structurer,
            settings=settings,
        )

    if isinstance(source, UrlSource):
        # ダウンロード前に重複チェックしておき、既知のURLなら無駄なダウンロードをしない。
        existing = repo.find_by_source_url(source.url)
        if existing is not None and repo.list_chunks(existing[0].id):
            item, record = existing
            logger.info("既にIngest済み(URL)なのでスキップ: %s", source.url)
            return IngestResult(item, record, repo.list_chunks(item.id), created=False)

        logger.info("Ingest開始(URL): %s", source.url)
        set_progress("stage", "PDFをダウンロード中…")
        try:
            pdf_bytes = await fetch_pdf(source.url, client=http_client, max_bytes=settings.ingest.max_pdf_bytes)
        finally:
            set_progress("stage", None)
        return await _ingest_from_pdf(
            pdf_bytes,
            source_url=source.url,
            embedder=embedder,
            extractor=extractor,
            repo=repo,
            settings=settings,
        )

    # UploadSource
    upload_path = Path(settings.ingest.upload_dir) / f"{source.upload_id}.pdf"
    try:
        pdf_bytes = await asyncio.to_thread(upload_path.read_bytes)
    except OSError as exc:
        msg = f"アップロードされたファイルが見つかりません(期限切れの可能性があります): {source.upload_id}"
        raise InvalidPaperUrlError(msg) from exc

    logger.info("Ingest開始(アップロード): upload_id=%s", source.upload_id)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    result = await _ingest_from_pdf(
        pdf_bytes,
        source_url=f"sha256:{digest}",
        embedder=embedder,
        extractor=extractor,
        repo=repo,
        settings=settings,
    )
    await asyncio.to_thread(upload_path.unlink, missing_ok=True)
    return result
