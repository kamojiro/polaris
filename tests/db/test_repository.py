"""PaperRepository の永続化テスト(一時 SQLite を使用)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import Item, ItemType, PaperRecord


def _make_paper(
    arxiv_id: str = "1706.03762",
    *,
    created_at: datetime | None = None,
) -> tuple[Item, PaperRecord]:
    now = created_at or datetime.now(UTC)
    record = PaperRecord(
        id=f"rec-{arxiv_id}",
        item_id=f"item-{arxiv_id}",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        doi=None,
        arxiv_id=arxiv_id,
        abstract="attention is all you need",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        ingested_at=now,
    )
    item = Item(
        id=f"item-{arxiv_id}",
        item_type=ItemType.paper,
        title="Attention Is All You Need",
        summary="attention is all you need",
        created_at=now,
        source_ref=f"paper:rec-{arxiv_id}",
    )
    return item, record


def test_save_and_list_papers(tmp_path: Path) -> None:
    """保存した論文が一覧に反映される."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper()

    repo.save_paper(item, record)
    papers = repo.list_papers()

    assert len(papers) == 1
    got_item, got_record = papers[0]
    assert got_item.title == "Attention Is All You Need"
    assert got_record.arxiv_id == "1706.03762"
    assert got_record.authors == ["Ashish Vaswani", "Noam Shazeer"]


def test_find_by_arxiv_id_hits_existing_record(tmp_path: Path) -> None:
    """arxiv_id で既存レコードを検索できる(重複防止のための前提)."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper()
    repo.save_paper(item, record)

    found = repo.find_by_arxiv_id("1706.03762")

    assert found is not None
    assert found[0].id == item.id


def test_find_by_arxiv_id_returns_none_when_missing(tmp_path: Path) -> None:
    """未保存の arxiv_id は None を返す."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.find_by_arxiv_id("9999.99999") is None


def test_list_papers_limit_returns_most_recent_first(tmp_path: Path) -> None:
    """Limit を指定すると、作成日時が新しい順に指定件数だけ返る."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    base = datetime.now(UTC)
    for i in range(5):
        item, record = _make_paper(f"1000.{i:05d}", created_at=base + timedelta(minutes=i))
        repo.save_paper(item, record)

    papers = repo.list_papers(limit=2)

    assert len(papers) == 2  # noqa: PLR2004
    assert [record.arxiv_id for _, record in papers] == ["1000.00004", "1000.00003"]


def test_count_papers_matches_total_saved(tmp_path: Path) -> None:
    """count_papers は limit に関係なく保存済みの総数を返す."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    for i in range(3):
        item, record = _make_paper(f"2000.{i:05d}")
        repo.save_paper(item, record)

    assert repo.count_papers() == 3  # noqa: PLR2004
    assert len(repo.list_papers(limit=1)) == 1
