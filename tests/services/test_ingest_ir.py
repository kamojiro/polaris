"""ingest_ir_document(EDINET Ingest)の純ロジックテスト(013-ir-analysis-domain).

tests/services/test_ingest_paper.py と同じ形を踏襲する。実LLMは使わず、フェイクの
IrMetadataExtractor を注入する。EDINETからのPDF取得は respx でモックする。
"""

from datetime import date
from pathlib import Path

import httpx
import respx

from polaris.agent.extract_ir_metadata import ExtractedIrDocument
from polaris.db.ir_repository import IrRepository
from polaris.db.session import create_db_engine
from polaris.services.ingest_ir import ingest_ir_document
from polaris.settings import IrSettings, Settings

_FIXTURE_DIR = Path(__file__).parent.parent / "adapters" / "fixtures"
_PDF_BYTES = (_FIXTURE_DIR / "attention.pdf").read_bytes()
_BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2"
_DOC_ID = "S100XXXX"


class _FakeIrExtractor:
    """固定の書誌情報・要約を返すだけのフェイク メタデータ抽出エージェント."""

    async def extract(self, *, body_head: str) -> ExtractedIrDocument:  # noqa: ARG002
        """本文冒頭の内容によらず固定のメタデータを返す."""
        return ExtractedIrDocument(
            filer_name="テスト株式会社",
            edinet_code="E00001",
            doc_type_code="有価証券報告書",
            period_start="2024-04-01",
            period_end="2025-03-31",
            submit_datetime="2025-06-27",
            summary="要約: テスト株式会社の有価証券報告書です。",
        )


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(ir=IrSettings(pdf_dir=str(tmp_path / "ir_pdfs"), edinet_api_key="test-key"))


def _make_repo(tmp_path: Path) -> IrRepository:
    engine = create_db_engine(str(tmp_path / "test.db"))
    return IrRepository(engine)


def _mock_edinet_pdf(*, status_code: int = 200) -> None:
    if status_code == 200:  # noqa: PLR2004
        respx.get(f"{_BASE_URL}/documents/{_DOC_ID}").mock(
            return_value=httpx.Response(200, content=_PDF_BYTES, headers={"content-type": "application/pdf"}),
        )
    else:
        respx.get(f"{_BASE_URL}/documents/{_DOC_ID}").mock(return_value=httpx.Response(status_code))


async def test_ingest_ir_document_persists_item_and_record(tmp_path: Path) -> None:
    """doc_id からPDFを取得し、Item / IrRecord が永続化される."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    with respx.mock:
        _mock_edinet_pdf()
        async with httpx.AsyncClient() as client:
            result = await ingest_ir_document(
                _DOC_ID,
                repo=repo,
                http_client=client,
                extractor=_FakeIrExtractor(),
                settings=settings,
            )

    assert result.created is True
    assert result.record.doc_id == _DOC_ID
    assert result.record.filer_name == "テスト株式会社"
    assert result.record.edinet_code == "E00001"
    assert result.record.period_start == date(2024, 4, 1)
    assert result.record.period_end == date(2025, 3, 31)
    assert result.record.submit_datetime.date() == date(2025, 6, 27)
    assert result.record.pdf_path is not None
    assert Path(result.record.pdf_path).exists()  # noqa: ASYNC240 - テストなのでブロッキング呼び出しで問題ない
    assert result.item.title == "テスト株式会社 有価証券報告書"
    assert result.item.summary == "要約: テスト株式会社の有価証券報告書です。"

    stored = repo.find_by_doc_id(_DOC_ID)
    assert stored is not None
    assert stored[0].id == result.item.id


async def test_ingest_ir_document_is_idempotent(tmp_path: Path) -> None:
    """同じ doc_id を2回投げても重複登録されない(再取得もしない)."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    with respx.mock:
        _mock_edinet_pdf()
        async with httpx.AsyncClient() as client:
            first = await ingest_ir_document(
                _DOC_ID,
                repo=repo,
                http_client=client,
                extractor=_FakeIrExtractor(),
                settings=settings,
            )
            second = await ingest_ir_document(
                _DOC_ID,
                repo=repo,
                http_client=client,
                extractor=_FakeIrExtractor(),
                settings=settings,
            )
        # 2回目は EDINET への HTTP リクエストを送っていない(1回しか呼ばれていない)ことを確認する。
        assert respx.calls.call_count == 1

    assert first.created is True
    assert second.created is False
    assert first.item.id == second.item.id
    assert len(repo.list_ir_documents()) == 1


async def test_ingest_ir_document_handles_missing_optional_fields(tmp_path: Path) -> None:
    """LLMがedinet_code/period等を読み取れなかった場合(null)でも取り込みが完了する."""
    repo = _make_repo(tmp_path)
    settings = _make_settings(tmp_path)

    class _MinimalExtractor:
        async def extract(self, *, body_head: str) -> ExtractedIrDocument:  # noqa: ARG002
            return ExtractedIrDocument(
                filer_name="不明な企業",
                edinet_code=None,
                doc_type_code=None,
                period_start=None,
                period_end=None,
                submit_datetime=None,
                summary="要約",
            )

    with respx.mock:
        _mock_edinet_pdf()
        async with httpx.AsyncClient() as client:
            result = await ingest_ir_document(
                _DOC_ID,
                repo=repo,
                http_client=client,
                extractor=_MinimalExtractor(),
                settings=settings,
            )

    assert result.created is True
    assert result.record.edinet_code is None
    assert result.record.period_start is None
    assert result.record.period_end is None
    # submit_datetime は読み取れなくても null にはできない(spec上必須項目)ため、Ingest時刻が入る。
    assert result.record.submit_datetime is not None
