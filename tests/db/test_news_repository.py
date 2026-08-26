"""NewsRepository の永続化テスト(一時 SQLite を使用)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polaris.db.news_repository import NewsRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import Item, ItemType, NewsRecord


def _make_news(
    news_id: str = "news-1",
    *,
    title: str = "記事タイトル",
    source_name: str = "Hacker News",
    source_label: str = "tech_industry_news",
    source_url: str = "https://example.com/news-1",
    published_at: datetime | None = None,
) -> tuple[Item, NewsRecord]:
    now = published_at or datetime.now(UTC)
    item = Item(
        id=f"item-{news_id}",
        item_type=ItemType.news_article,
        title=title,
        summary="要約",
        created_at=now,
        source_ref=f"news:rec-{news_id}",
    )
    record = NewsRecord(
        id=f"rec-{news_id}",
        item_id=f"item-{news_id}",
        source_name=source_name,
        source_label=source_label,
        published_at=now,
        source_url=source_url,
    )
    return item, record


def test_save_and_list_news(tmp_path: Path) -> None:
    """保存したニュースが一覧に反映される."""
    repo = NewsRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_news(title="ある記事", source_label="ai_llm")

    repo.save_news(item, record)
    news = repo.list_news()

    assert len(news) == 1
    got_item, got_record = news[0]
    assert got_item.title == "ある記事"
    assert got_record.source_label == "ai_llm"


def test_list_news_orders_by_published_at_descending(tmp_path: Path) -> None:
    """公開日時が新しいものが先頭に来る."""
    repo = NewsRepository(create_db_engine(str(tmp_path / "test.db")))
    base = datetime.now(UTC)
    for i in range(3):
        item, record = _make_news(
            f"news-{i}", source_url=f"https://example.com/news-{i}", published_at=base + timedelta(minutes=i)
        )
        repo.save_news(item, record)

    news = repo.list_news()

    assert [item.id for item, _ in news] == ["item-news-2", "item-news-1", "item-news-0"]


def test_list_news_respects_limit(tmp_path: Path) -> None:
    """limitを指定するとSQL LIMITで件数が絞られる."""
    repo = NewsRepository(create_db_engine(str(tmp_path / "test.db")))
    for i in range(5):
        item, record = _make_news(f"news-{i}", source_url=f"https://example.com/news-{i}")
        repo.save_news(item, record)

    news = repo.list_news(limit=2)

    assert len(news) == 2  # noqa: PLR2004


def test_find_by_source_url_returns_none_when_missing(tmp_path: Path) -> None:
    """未保存のsource_urlはNoneを返す(冪等なIngestの重複チェックに使う)."""
    repo = NewsRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.find_by_source_url("https://example.com/does-not-exist") is None


def test_find_by_source_url_returns_saved_record(tmp_path: Path) -> None:
    """保存済みのsource_urlは対応するItem/NewsRecordを返す."""
    repo = NewsRepository(create_db_engine(str(tmp_path / "test.db")))
    item, record = _make_news(source_url="https://example.com/target")
    repo.save_news(item, record)

    found = repo.find_by_source_url("https://example.com/target")

    assert found is not None
    assert found[0].id == item.id
