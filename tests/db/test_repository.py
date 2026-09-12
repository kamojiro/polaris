"""PaperRepository の永続化テスト(一時 SQLite を使用)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import Session

from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import Item, ItemType, PaperRecord, PaperResearchDiscoveredPaper

if TYPE_CHECKING:
    from sqlalchemy import Engine


def _make_paper(
    arxiv_id: str = "1706.03762",
    *,
    title: str = "Attention Is All You Need",
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
        title=title,
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


def test_search_papers_matches_by_arxiv_id(tmp_path: Path) -> None:
    """arxiv_id の完全一致で検索できる(015-paper-qa-chat)."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper()
    repo.save_paper(item, record)

    results = repo.search_papers("1706.03762")

    assert len(results) == 1
    assert results[0][0].id == item.id


def test_search_papers_matches_by_title_substring_case_insensitive(tmp_path: Path) -> None:
    """タイトルの部分一致(大小無視)で検索できる."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper()
    repo.save_paper(item, record)

    results = repo.search_papers("attention is all")

    assert len(results) == 1
    assert results[0][0].id == item.id


def test_search_papers_returns_empty_when_no_match(tmp_path: Path) -> None:
    """該当する論文が無ければ空リストを返す."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_paper()
    repo.save_paper(item, record)

    assert repo.search_papers("nonexistent paper title") == []


def test_search_papers_limit_and_order(tmp_path: Path) -> None:
    """Limit を指定すると、作成日時が新しい順に指定件数だけ返る."""
    repo = PaperRepository(create_db_engine(str(tmp_path / "test.db")))
    base = datetime.now(UTC)
    for i in range(3):
        item, record = _make_paper(
            f"3000.{i:05d}",
            title=f"Common Title {i}",
            created_at=base + timedelta(minutes=i),
        )
        repo.save_paper(item, record)

    results = repo.search_papers("Common Title", limit=2)

    assert len(results) == 2  # noqa: PLR2004
    assert [record.arxiv_id for _, record in results] == ["3000.00002", "3000.00001"]


def _mark_discovered(engine: Engine, item_id: str, *, research_id: str = "research-1") -> None:
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            PaperResearchDiscoveredPaper(
                id=f"discovered-{item_id}",
                item_id=item_id,
                research_id=research_id,
                discovered_at=datetime.now(UTC),
            )
        )
        session.commit()


def test_list_papers_excludes_discovered_by_default(tmp_path: Path) -> None:
    """027の自動取り込みで出自のある論文は list_papers から除外される(2026-09-12)."""
    engine = create_db_engine(str(tmp_path / "test.db"))
    repo = PaperRepository(engine)
    item, record = _make_paper()
    repo.save_paper(item, record)
    _mark_discovered(engine, item.id)

    assert repo.list_papers() == []
    included = repo.list_papers(include_discovered=True)
    assert [got_item.id for got_item, _ in included] == [item.id]


def test_count_papers_excludes_discovered_by_default(tmp_path: Path) -> None:
    """出自のある論文は count_papers からも除外され、一覧の件数と一致する."""
    engine = create_db_engine(str(tmp_path / "test.db"))
    repo = PaperRepository(engine)
    item, record = _make_paper()
    repo.save_paper(item, record)
    _mark_discovered(engine, item.id)

    assert repo.count_papers() == 0
    assert repo.count_papers(include_discovered=True) == 1


def test_list_papers_created_between_excludes_discovered_by_default(tmp_path: Path) -> None:
    """023の日次要約が調査で自動取り込みした論文で埋まらないよう、期間検索でも除外される."""
    engine = create_db_engine(str(tmp_path / "test.db"))
    repo = PaperRepository(engine)
    now = datetime.now(UTC)
    item, record = _make_paper(created_at=now)
    repo.save_paper(item, record)
    _mark_discovered(engine, item.id)

    start, end = now - timedelta(minutes=1), now + timedelta(minutes=1)
    assert repo.list_papers_created_between(start, end) == []
    included = repo.list_papers_created_between(start, end, include_discovered=True)
    assert [got_item.id for got_item, _ in included] == [item.id]


def test_search_papers_still_finds_discovered_papers(tmp_path: Path) -> None:
    """search_papers は除外しない(調査で取り込んだ論文についても聞けるように)."""
    engine = create_db_engine(str(tmp_path / "test.db"))
    repo = PaperRepository(engine)
    item, record = _make_paper()
    repo.save_paper(item, record)
    _mark_discovered(engine, item.id)

    results = repo.search_papers("1706.03762")

    assert len(results) == 1
    assert results[0][0].id == item.id
