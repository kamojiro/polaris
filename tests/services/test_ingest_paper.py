"""ingest_paper_from_url(フルパイプライン)の純ロジックテスト.

実LLM・実Embeddingモデルは使わず、フェイクの EmbeddingModel / PaperStructurer /
PaperMetadataExtractor を注入する。arXiv・URL直リンクのメタデータ取得・PDF
ダウンロードは respx でモックする。
"""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy.exc import IntegrityError

from polaris.adapters.pdf.extractor import PdfExtractionError
from polaris.agent.extract_metadata import ExtractedPaper
from polaris.agent.structure_paper import StructuredPaper
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import Item, ItemType, PaperRecord
from polaris.services.ingest_paper import ingest_paper_from_url
from polaris.services.paper_source import InvalidPaperUrlError
from polaris.settings import IngestSettings, Settings

_FIXTURE_DIR = Path(__file__).parent.parent / "adapters"
_METADATA_XML = (_FIXTURE_DIR / "fixture_1706.03762.xml").read_text(encoding="utf-8")
_PDF_BYTES = (_FIXTURE_DIR / "fixtures" / "attention.pdf").read_bytes()
_URL = "https://arxiv.org/abs/1706.03762"
_EMBEDDING_DIM = 4


class _FakeEmbedder:
    """固定ベクトルを返すだけのフェイク Embedding モデル."""

    model_id = "fake-embedder"

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """テキスト数と同じ数だけ固定ベクトルを返す."""
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class _FakeStructurer:
    """固定の summary/venue を返すだけのフェイク Structure エージェント."""

    async def structure(self, *, title: str, abstract: str, comment: str | None) -> StructuredPaper:  # noqa: ARG002
        """Title を使った固定 summary、venue は常に None を返す."""
        return StructuredPaper(summary=f"要約: {title}", venue=None)


class _FakeExtractor:
    """固定の書誌情報・要約を返すだけのフェイク メタデータ抽出エージェント."""

    async def extract(self, *, body_head: str) -> ExtractedPaper:  # noqa: ARG002
        """本文冒頭の内容によらず固定のメタデータを返す."""
        return ExtractedPaper(
            title="Fake Paper Title",
            authors=["Fake Author"],
            year=2024,
            abstract="fake abstract",
            doi=None,
            venue=None,
            summary="要約: Fake Paper Title",
        )


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        ingest=IngestSettings(
            pdf_dir=str(tmp_path / "pdfs"),
            upload_dir=str(tmp_path / "uploads"),
            embedding_model_id="fake-embedder",
            embedding_dim=_EMBEDDING_DIM,
            chunk_chars=200,
            chunk_overlap_chars=20,
        ),
    )


def _make_repo(tmp_path: Path) -> PaperRepository:
    engine = create_db_engine(str(tmp_path / "test.db"), embedding_dim=_EMBEDDING_DIM)
    return PaperRepository(engine)


def _mock_arxiv_metadata() -> None:
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=_METADATA_XML))


def _mock_arxiv_pdf(*, status_code: int = 200) -> None:
    if status_code == 200:  # noqa: PLR2004
        respx.get("https://arxiv.org/pdf/1706.03762").mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/pdf"}),
        )
    else:
        respx.get("https://arxiv.org/pdf/1706.03762").mock(return_value=httpx.Response(status_code))


async def test_ingest_paper_persists_item_record_chunks_and_embeddings(tmp_path: Path) -> None:
    """フルパイプラインで Item / PaperRecord / Chunk / Embedding がすべて永続化される."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    with respx.mock:
        _mock_arxiv_metadata()
        _mock_arxiv_pdf()
        async with httpx.AsyncClient() as client:
            result = await ingest_paper_from_url(
                _URL,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )

    assert result.created is True
    assert result.item.title == "Attention Is All You Need"
    assert result.item.summary == "要約: Attention Is All You Need"
    assert result.record.arxiv_id == "1706.03762"
    assert result.record.pdf_path is not None
    assert Path(result.record.pdf_path).exists()  # noqa: ASYNC240 - テストなのでブロッキング呼び出しで問題ない
    assert len(result.chunks) > 1  # 22個の見出しを含む本文なので複数チャンクになるはず

    stored_chunks = repo.list_chunks(result.item.id)
    assert len(stored_chunks) == len(result.chunks)

    with repo._engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT count(*) FROM embeddings").fetchone()
    assert rows is not None
    assert rows[0] == len(result.chunks)


async def test_ingest_paper_falls_back_to_abstract_when_pdf_fails(tmp_path: Path) -> None:
    """PDF取得に失敗しても abstract ベースで1チャンクとして続行する."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    with respx.mock:
        _mock_arxiv_metadata()
        _mock_arxiv_pdf(status_code=500)
        async with httpx.AsyncClient() as client:
            result = await ingest_paper_from_url(
                _URL,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )

    assert result.created is True
    assert result.record.pdf_path is None
    assert len(result.chunks) == 1
    assert result.chunks[0].section is None
    assert result.chunks[0].text == result.record.abstract


async def test_ingest_paper_is_idempotent(tmp_path: Path) -> None:
    """同じ ArXiv URL を2回投げても重複登録されない(チャンクまで存在すればスキップ)."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    with respx.mock:
        _mock_arxiv_metadata()
        _mock_arxiv_pdf()
        async with httpx.AsyncClient() as client:
            first = await ingest_paper_from_url(
                _URL,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )
            second = await ingest_paper_from_url(
                _URL,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )

    assert first.created is True
    assert second.created is False
    assert first.item.id == second.item.id
    assert len(repo.list_papers()) == 1


async def test_ingest_paper_normalizes_source_url_to_abs(tmp_path: Path) -> None:
    """貼られた URL の形(/pdf/・バージョン付き)によらず source_url は /abs/ に揃う."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)
    pasted_url = "https://arxiv.org/pdf/1706.03762v7"

    with respx.mock:
        _mock_arxiv_metadata()
        _mock_arxiv_pdf()
        async with httpx.AsyncClient() as client:
            result = await ingest_paper_from_url(
                pasted_url,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )

    assert result.record.source_url == "https://arxiv.org/abs/1706.03762"


class _RaceyRepository(PaperRepository):
    """1回目の save_paper 呼び出し時に、別リクエストが先に確定した競合状態を模倣する.

    find_by_arxiv_id で「無い」と判定してから保存するまではアトミックではないため、
    同じ arxiv_id を同時に取り込もうとする2つのリクエストが両方とも新規作成に
    進んでしまうことがある。ここでは実際にそれを再現するのではなく、
    「別リクエストがちょうど先に確定した」状況を直接注入して検証する。
    """

    def __init__(self, engine: object, winner_item: Item, winner_record: PaperRecord) -> None:
        super().__init__(engine)  # type: ignore[arg-type]
        self._winner_item = winner_item
        self._winner_record = winner_record
        self._triggered = False

    def save_paper(self, item: Item, record: PaperRecord) -> None:
        """1回目だけ勝者のレコードを先に保存し、IntegrityError を送出する."""
        if not self._triggered:
            self._triggered = True
            super().save_paper(self._winner_item, self._winner_record)
            statement = "INSERT"
            msg = "UNIQUE constraint failed: paper_records.arxiv_id"
            raise IntegrityError(statement, {}, Exception(msg))
        super().save_paper(item, record)


async def test_ingest_paper_switches_to_winner_on_concurrent_insert_conflict(tmp_path: Path) -> None:
    """同じ arxiv_id への同時保存で UNIQUE 制約違反が起きても、先に確定した方に切り替えて続行する."""
    now = datetime.now(UTC)
    winner_record = PaperRecord(
        id="winner-rec",
        item_id="winner-item",
        authors=["Someone Else"],
        year=2017,
        arxiv_id="1706.03762",
        abstract="raced abstract",
        source_url="https://arxiv.org/abs/1706.03762",
        ingested_at=now,
    )
    winner_item = Item(
        id="winner-item",
        item_type=ItemType.paper,
        title="Attention Is All You Need",
        summary="raced abstract",
        created_at=now,
        source_ref="paper:winner-rec",
    )
    engine = create_db_engine(str(tmp_path / "test.db"), embedding_dim=_EMBEDDING_DIM)
    repo = _RaceyRepository(engine, winner_item, winner_record)
    settings = _make_settings(tmp_path)

    with respx.mock:
        _mock_arxiv_metadata()
        _mock_arxiv_pdf()
        async with httpx.AsyncClient() as client:
            result = await ingest_paper_from_url(
                _URL,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )

    # 自分で組み立てたレコードではなく、先に確定した勝者のレコードに紐づいて続行していること。
    assert result.item.id == "winner-item"
    assert result.record.id == "winner-rec"
    assert len(repo.list_papers()) == 1  # 重複した Item/PaperRecord が残っていない
    assert len(result.chunks) > 0
    stored_chunks = repo.list_chunks("winner-item")
    assert len(stored_chunks) == len(result.chunks)


async def test_ingest_paper_rejects_non_arxiv_url(tmp_path: Path) -> None:
    """ArXiv の URL / ID、PDF直リンク、upload:// のいずれとしても解釈できない入力は InvalidPaperUrlError になる."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    async with httpx.AsyncClient() as client:
        with pytest.raises(InvalidPaperUrlError):
            await ingest_paper_from_url(
                "not a url or id",
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )


async def test_ingest_paper_from_pdf_url(tmp_path: Path) -> None:
    """非arXivのPDF直リンクURLから取り込むと、メタデータ抽出結果が Item/PaperRecord に反映される."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)
    pdf_url = "https://example.com/papers/some-paper.pdf"

    with respx.mock:
        respx.get(pdf_url).mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/pdf"}),
        )
        async with httpx.AsyncClient() as client:
            result = await ingest_paper_from_url(
                pdf_url,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )

    assert result.created is True
    assert result.item.title == "Fake Paper Title"
    assert result.item.summary == "要約: Fake Paper Title"
    assert result.record.arxiv_id is None
    assert result.record.source_url == pdf_url
    assert result.record.pdf_path is not None
    assert Path(result.record.pdf_path).exists()  # noqa: ASYNC240 - テストなのでブロッキング呼び出しで問題ない
    assert len(result.chunks) > 0


async def test_ingest_paper_from_pdf_url_is_idempotent(tmp_path: Path) -> None:
    """同じPDF直リンクURLを2回投げても重複登録されない(source_urlで判定)."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)
    pdf_url = "https://example.com/papers/some-paper.pdf"

    with respx.mock:
        respx.get(pdf_url).mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/pdf"}),
        )
        async with httpx.AsyncClient() as client:
            first = await ingest_paper_from_url(
                pdf_url,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )
            second = await ingest_paper_from_url(
                pdf_url,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )

    assert first.created is True
    assert second.created is False
    assert first.item.id == second.item.id
    assert len(repo.list_papers()) == 1


async def test_ingest_paper_from_pdf_url_raises_when_extraction_fails(tmp_path: Path) -> None:
    """非arXivは本文抽出に失敗するとabstractフォールバックが無いため例外を送出する."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)
    pdf_url = "https://example.com/papers/corrupt.pdf"
    corrupt_bytes = (_FIXTURE_DIR / "fixtures" / "corrupt.pdf").read_bytes()

    with respx.mock:
        respx.get(pdf_url).mock(
            return_value=httpx.Response(200, content=corrupt_bytes, headers={"content-type": "application/pdf"}),
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(PdfExtractionError):
                await ingest_paper_from_url(
                    pdf_url,
                    repo=repo,
                    http_client=client,
                    embedder=_FakeEmbedder(),
                    structurer=_FakeStructurer(),
                    extractor=_FakeExtractor(),
                    settings=settings,
                )


async def test_ingest_paper_from_upload(tmp_path: Path) -> None:
    """アップロード済みのローカルPDF(upload://)から取り込め、取り込み後にステージングファイルが削除される."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)
    upload_dir = Path(settings.ingest.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - テストなのでブロッキング呼び出しで問題ない
    upload_id = "test-upload-id"
    upload_path = upload_dir / f"{upload_id}.pdf"
    upload_path.write_bytes(_PDF_BYTES)

    async with httpx.AsyncClient() as client:
        result = await ingest_paper_from_url(
            f"upload://{upload_id}",
            repo=repo,
            http_client=client,
            embedder=_FakeEmbedder(),
            structurer=_FakeStructurer(),
            extractor=_FakeExtractor(),
            settings=settings,
        )

    assert result.created is True
    assert result.item.title == "Fake Paper Title"
    assert result.record.arxiv_id is None
    assert result.record.source_url is not None
    assert result.record.source_url.startswith("sha256:")
    assert len(result.chunks) > 0
    assert not upload_path.exists()


async def test_ingest_paper_from_upload_missing_file_raises(tmp_path: Path) -> None:
    """アップロードIDに対応するファイルが無ければ InvalidPaperUrlError になる."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    async with httpx.AsyncClient() as client:
        with pytest.raises(InvalidPaperUrlError):
            await ingest_paper_from_url(
                "upload://does-not-exist",
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                extractor=_FakeExtractor(),
                settings=settings,
            )
