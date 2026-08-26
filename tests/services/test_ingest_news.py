"""ingest_all_feeds(RSS Ingestパイプライン)の純ロジックテスト.

実LLMは使わず、フェイクの NewsStructurer を注入する(tests/services/test_ingest_paper.py
と同じパターン)。フィードのHTTP取得はrespxでモックする。
"""

from pathlib import Path

import httpx
import respx

from polaris.agent.structure_news import StructuredNews
from polaris.db.news_repository import NewsRepository
from polaris.db.session import create_db_engine
from polaris.services.ingest_news import ingest_all_feeds
from polaris.settings import NewsFeed, NewsSettings, Settings

_FIXTURE_DIR = Path(__file__).parent.parent / "adapters" / "fixtures"
_RSS_BYTES = (_FIXTURE_DIR / "feed_rss.xml").read_bytes()
_ATOM_BYTES = (_FIXTURE_DIR / "feed_atom.xml").read_bytes()

_FEED_A_URL = "https://example.com/feed-a"
_FEED_B_URL = "https://example.com/feed-b"


class _FakeNewsStructurer:
    """固定の summary を返すだけのフェイクStructureエージェント."""

    async def structure(self, *, title: str, summary: str) -> StructuredNews:
        del summary
        return StructuredNews(summary=f"要約: {title}")


def _make_settings(tmp_path: Path, feeds: list[NewsFeed]) -> Settings:
    return Settings(
        DB_PATH=str(tmp_path / "test.db"),
        news=NewsSettings(feeds=feeds, max_entries_per_feed=20),
    )


def _make_repo(tmp_path: Path) -> NewsRepository:
    engine = create_db_engine(str(tmp_path / "test.db"))
    return NewsRepository(engine)


async def test_ingest_all_feeds_persists_new_entries(tmp_path: Path) -> None:
    """新規記事がItem/NewsRecordとして保存される."""
    feeds = [NewsFeed(name="Feed A", url=_FEED_A_URL, label="tech_industry_news")]
    settings = _make_settings(tmp_path, feeds)
    repo = _make_repo(tmp_path)
    structurer = _FakeNewsStructurer()

    with respx.mock:
        respx.get(_FEED_A_URL).mock(return_value=httpx.Response(200, content=_RSS_BYTES))
        async with httpx.AsyncClient() as client:
            result = await ingest_all_feeds(repo=repo, structurer=structurer, http_client=client, settings=settings)

    assert result.created > 0
    assert result.failed == 0
    saved = repo.list_news()
    assert len(saved) == result.created
    assert saved[0][1].source_label == "tech_industry_news"


async def test_ingest_all_feeds_skips_existing_entries_on_rerun(tmp_path: Path) -> None:
    """同じフィードを2回取り込んでも重複保存されず、2回目はskippedにカウントされる(冪等性)."""
    feeds = [NewsFeed(name="Feed A", url=_FEED_A_URL, label="tech_industry_news")]
    settings = _make_settings(tmp_path, feeds)
    repo = _make_repo(tmp_path)
    structurer = _FakeNewsStructurer()

    with respx.mock:
        respx.get(_FEED_A_URL).mock(return_value=httpx.Response(200, content=_RSS_BYTES))
        async with httpx.AsyncClient() as client:
            first = await ingest_all_feeds(repo=repo, structurer=structurer, http_client=client, settings=settings)
            second = await ingest_all_feeds(repo=repo, structurer=structurer, http_client=client, settings=settings)

    assert first.created > 0
    assert second.created == 0
    assert second.skipped == first.created


async def test_ingest_all_feeds_one_feed_failure_does_not_block_others(tmp_path: Path) -> None:
    """1フィードのHTTP取得失敗が他フィードの処理を止めない."""
    feeds = [
        NewsFeed(name="Broken", url=_FEED_A_URL, label="tech_industry_news"),
        NewsFeed(name="Working", url=_FEED_B_URL, label="swe_general"),
    ]
    settings = _make_settings(tmp_path, feeds)
    repo = _make_repo(tmp_path)
    structurer = _FakeNewsStructurer()

    with respx.mock:
        respx.get(_FEED_A_URL).mock(return_value=httpx.Response(500))
        respx.get(_FEED_B_URL).mock(return_value=httpx.Response(200, content=_ATOM_BYTES))
        async with httpx.AsyncClient() as client:
            result = await ingest_all_feeds(repo=repo, structurer=structurer, http_client=client, settings=settings)

    assert result.failed == 1
    assert result.created > 0  # Feed B分は取り込めている
