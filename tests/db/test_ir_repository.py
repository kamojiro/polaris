"""IrRepository の永続化テスト(一時 SQLite を使用、013-ir-analysis-domain).

tests/db/test_repository.py(PaperRepository)と同じ形を踏襲する。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polaris.db.ir_repository import IrRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import IrRecord, Item, ItemType


def _make_ir_document(
    doc_id: str = "S100XXXX",
    *,
    filer_name: str = "テスト株式会社",
    created_at: datetime | None = None,
) -> tuple[Item, IrRecord]:
    now = created_at or datetime.now(UTC)
    record = IrRecord(
        id=f"rec-{doc_id}",
        item_id=f"item-{doc_id}",
        doc_id=doc_id,
        filer_name=filer_name,
        edinet_code="E00001",
        doc_type_code="有価証券報告書",
        period_start=None,
        period_end=None,
        submit_datetime=now,
        pdf_path=None,
        ingested_at=now,
    )
    item = Item(
        id=f"item-{doc_id}",
        item_type=ItemType.ir_document,
        title=f"{filer_name} 有価証券報告書",
        summary="要約",
        created_at=now,
        source_ref=f"ir_document:rec-{doc_id}",
    )
    return item, record


def test_save_and_list_ir_documents(tmp_path: Path) -> None:
    """保存したIR文書が一覧に反映される."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_ir_document()

    repo.save_ir_document(item, record)
    documents = repo.list_ir_documents()

    assert len(documents) == 1
    got_item, got_record = documents[0]
    assert got_item.title == "テスト株式会社 有価証券報告書"
    assert got_record.doc_id == "S100XXXX"
    assert got_record.filer_name == "テスト株式会社"


def test_find_by_doc_id_hits_existing_record(tmp_path: Path) -> None:
    """doc_id で既存レコードを検索できる(重複防止のための前提)."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_ir_document()
    repo.save_ir_document(item, record)

    found = repo.find_by_doc_id("S100XXXX")

    assert found is not None
    assert found[0].id == item.id


def test_find_by_doc_id_returns_none_when_missing(tmp_path: Path) -> None:
    """未保存の doc_id は None を返す."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.find_by_doc_id("S199YYYY") is None


def test_list_ir_documents_limit_returns_most_recent_first(tmp_path: Path) -> None:
    """Limit を指定すると、作成日時が新しい順に指定件数だけ返る."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    base = datetime.now(UTC)
    for i in range(5):
        item, record = _make_ir_document(f"S100{i:04d}", created_at=base + timedelta(minutes=i))
        repo.save_ir_document(item, record)

    documents = repo.list_ir_documents(limit=2)

    assert len(documents) == 2  # noqa: PLR2004
    assert [record.doc_id for _, record in documents] == ["S1000004", "S1000003"]


def test_count_ir_documents_matches_total_saved(tmp_path: Path) -> None:
    """count_ir_documents は limit に関係なく保存済みの総数を返す."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    for i in range(3):
        item, record = _make_ir_document(f"S200{i:04d}")
        repo.save_ir_document(item, record)

    assert repo.count_ir_documents() == 3  # noqa: PLR2004
    assert len(repo.list_ir_documents(limit=1)) == 1


def test_search_ir_documents_matches_by_doc_id(tmp_path: Path) -> None:
    """doc_id の完全一致で検索できる."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_ir_document()
    repo.save_ir_document(item, record)

    results = repo.search_ir_documents("S100XXXX")

    assert len(results) == 1
    assert results[0][0].id == item.id


def test_search_ir_documents_matches_by_filer_name_substring_case_insensitive(tmp_path: Path) -> None:
    """企業名(filer_name)の部分一致(大小無視)で検索できる."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_ir_document(filer_name="Example Corp")
    repo.save_ir_document(item, record)

    results = repo.search_ir_documents("example")

    assert len(results) == 1
    assert results[0][0].id == item.id


def test_search_ir_documents_returns_empty_when_no_match(tmp_path: Path) -> None:
    """該当するIR文書が無ければ空リストを返す."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_ir_document()
    repo.save_ir_document(item, record)

    assert repo.search_ir_documents("nonexistent company") == []


def test_search_ir_documents_limit_and_order(tmp_path: Path) -> None:
    """Limit を指定すると、作成日時が新しい順に指定件数だけ返る."""
    repo = IrRepository(create_db_engine(str(tmp_path / "test.db")))
    base = datetime.now(UTC)
    for i in range(3):
        item, record = _make_ir_document(
            f"S300{i:04d}",
            filer_name="Common Corp",
            created_at=base + timedelta(minutes=i),
        )
        repo.save_ir_document(item, record)

    results = repo.search_ir_documents("Common Corp", limit=2)

    assert len(results) == 2  # noqa: PLR2004
    assert [record.doc_id for _, record in results] == ["S3000002", "S3000001"]
