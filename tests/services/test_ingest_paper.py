"""ingest_paper_from_url(フルパイプライン)の純ロジックテスト.

実LLM・実Embeddingモデルは使わず、フェイクの EmbeddingModel / PaperStructurer を
注入する。arXiv のメタデータ取得・PDF ダウンロードは respx でモックする。
"""

from pathlib import Path

import httpx
import pytest
import respx

from polaris.agent.structure_paper import StructuredPaper
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.services.ingest_paper import InvalidPaperUrlError, ingest_paper_from_url
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


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        ingest=IngestSettings(
            pdf_dir=str(tmp_path / "pdfs"),
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
                settings=settings,
            )
            second = await ingest_paper_from_url(
                _URL,
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
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
                settings=settings,
            )

    assert result.record.source_url == "https://arxiv.org/abs/1706.03762"


async def test_ingest_paper_rejects_non_arxiv_url(tmp_path: Path) -> None:
    """ArXiv の URL / ID として解釈できない入力は InvalidPaperUrlError になる."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    async with httpx.AsyncClient() as client:
        with pytest.raises(InvalidPaperUrlError):
            await ingest_paper_from_url(
                "https://example.com/not-a-paper",
                repo=repo,
                http_client=client,
                embedder=_FakeEmbedder(),
                structurer=_FakeStructurer(),
                settings=settings,
            )
