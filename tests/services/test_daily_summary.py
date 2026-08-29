"""daily_summary(日次サマリー集計・生成)の純ロジックテスト.

実LLMは使わず、フェイクの DailySummarizer を注入する(tests/services/test_ingest_news.py
と同じパターン)。JSTの日付境界がUTC保存値と正しく対応することが一番バグりやすいため
厚めに検証する。
"""

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from polaris.db.daily_summary_repository import DailySummaryRepository
from polaris.db.memory_repository import MemoryRepository
from polaris.db.news_repository import NewsRepository
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.db.todo_repository import TodoRepository
from polaris.domain.entities import Item, ItemType, NewsRecord, PaperRecord, TodoRecord, TodoScale
from polaris.services.daily_summary import collect_activity, generate_daily_summary, local_day_bounds_utc
from polaris.settings import NewsFeed, NewsSettings, Settings

_JST = ZoneInfo("Asia/Tokyo")
_DAY = date(2026, 8, 30)


class _FakeDailySummarizer:
    """渡されたプロンプトをそのまま記録するだけのフェイク要約エージェント."""

    def __init__(self) -> None:
        self.received_prompts: list[str] = []

    async def summarize(self, activity_prompt: str) -> str:
        self.received_prompts.append(activity_prompt)
        return f"要約: {len(activity_prompt)}文字分の活動がありました。"


def _make_settings(tmp_path: Path, *, feeds: list[NewsFeed] | None = None) -> Settings:
    return Settings(
        DB_PATH=str(tmp_path / "test.db"),
        news=NewsSettings(feeds=feeds if feeds is not None else []),
    )


def _make_repos(
    tmp_path: Path,
) -> tuple[PaperRepository, TodoRepository, MemoryRepository, NewsRepository, DailySummaryRepository]:
    engine = create_db_engine(str(tmp_path / "test.db"))
    return (
        PaperRepository(engine),
        TodoRepository(engine),
        MemoryRepository(engine),
        NewsRepository(engine),
        DailySummaryRepository(engine),
    )


def _save_paper(repo: PaperRepository, *, title: str, created_at: datetime) -> None:
    item_id = uuid.uuid4().hex
    item = Item(
        id=item_id, item_type=ItemType.paper, title=title, summary="論文の要約", created_at=created_at,
        source_ref=f"paper:{item_id}",
    )
    record = PaperRecord(id=uuid.uuid4().hex, item_id=item_id, ingested_at=created_at)
    repo.save_paper(item, record)


def _save_todo(
    repo: TodoRepository, *, title: str, created_at: datetime, completed_at: datetime | None = None
) -> None:
    item_id = uuid.uuid4().hex
    item = Item(
        id=item_id, item_type=ItemType.todo, title=title, summary="", created_at=created_at,
        source_ref=f"todo:{item_id}",
    )
    record = TodoRecord(
        id=uuid.uuid4().hex, item_id=item_id, scale=TodoScale.day, updated_at=created_at, completed_at=completed_at
    )
    repo.save_todo(item, record)


def _save_news(
    repo: NewsRepository, *, title: str, source_name: str, source_label: str, created_at: datetime
) -> None:
    item_id = uuid.uuid4().hex
    item = Item(
        id=item_id, item_type=ItemType.news_article, title=title, summary="記事の要約", created_at=created_at,
        source_ref=f"news:{item_id}",
    )
    record = NewsRecord(
        id=uuid.uuid4().hex, item_id=item_id, source_name=source_name, source_label=source_label,
        published_at=created_at, source_url=f"https://example.com/{item_id}",
    )
    repo.save_news(item, record)


def test_local_day_bounds_utc_converts_jst_day_to_utc_range() -> None:
    """JST 8/30 00:00〜翌日00:00がUTC 8/29 15:00〜8/30 15:00に対応する(JST=UTC+9)."""
    start, end = local_day_bounds_utc(_DAY, tz_name="Asia/Tokyo")

    assert start == datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
    assert end == datetime(2026, 8, 30, 15, 0, tzinfo=UTC)


def test_collect_activity_excludes_paper_created_just_before_jst_midnight(tmp_path: Path) -> None:
    """JST 8/29 23:30に作られた論文は8/30の集計に混ざらない(日付境界の正しさの核心)."""
    paper_repo, todo_repo, memory_repo, news_repo, _summary_repo = _make_repos(tmp_path)
    settings = _make_settings(tmp_path)
    just_before = datetime(2026, 8, 29, 23, 30, tzinfo=_JST).astimezone(UTC)
    _save_paper(paper_repo, title="前日の論文", created_at=just_before)

    activity = collect_activity(
        day=_DAY, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo, news_repo=news_repo,
        settings=settings,
    )

    assert activity.papers == []


def test_collect_activity_includes_paper_created_just_after_jst_midnight(tmp_path: Path) -> None:
    """JST 8/30 00:30に作られた論文は8/30の集計に含まれる."""
    paper_repo, todo_repo, memory_repo, news_repo, _summary_repo = _make_repos(tmp_path)
    settings = _make_settings(tmp_path)
    just_after = datetime(2026, 8, 30, 0, 30, tzinfo=_JST).astimezone(UTC)
    _save_paper(paper_repo, title="当日の論文", created_at=just_after)

    activity = collect_activity(
        day=_DAY, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo, news_repo=news_repo,
        settings=settings,
    )

    assert [item.title for item, _record in activity.papers] == ["当日の論文"]


def test_collect_activity_picks_up_added_and_completed_todos(tmp_path: Path) -> None:
    """当日追加のTODOと当日完了のTODOが両方拾われる(異なるTODOの場合)."""
    paper_repo, todo_repo, memory_repo, news_repo, _summary_repo = _make_repos(tmp_path)
    settings = _make_settings(tmp_path)
    noon = datetime(2026, 8, 30, 12, 0, tzinfo=_JST).astimezone(UTC)
    old = datetime(2026, 8, 20, 12, 0, tzinfo=_JST).astimezone(UTC)
    _save_todo(todo_repo, title="今日追加したTODO", created_at=noon)
    _save_todo(todo_repo, title="昔追加して今日完了したTODO", created_at=old, completed_at=noon)

    activity = collect_activity(
        day=_DAY, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo, news_repo=news_repo,
        settings=settings,
    )

    assert [item.title for item, _record in activity.todos_added] == ["今日追加したTODO"]
    assert [item.title for item, _record in activity.todos_completed] == ["昔追加して今日完了したTODO"]


def test_collect_activity_separates_catalog_news_from_summarized_news(tmp_path: Path) -> None:
    """skip_summary=Trueのフィード由来はnewsではなくcatalog_news_countsに入る."""
    paper_repo, todo_repo, memory_repo, news_repo, _summary_repo = _make_repos(tmp_path)
    feeds = [
        NewsFeed(name="Catalog Feed", url="https://example.com/catalog", label="ai_llm", skip_summary=True),
        NewsFeed(name="Blog Feed", url="https://example.com/blog", label="swe_general"),
    ]
    settings = _make_settings(tmp_path, feeds=feeds)
    noon = datetime(2026, 8, 30, 12, 0, tzinfo=_JST).astimezone(UTC)
    _save_news(news_repo, title="カタログ記事1", source_name="Catalog Feed", source_label="ai_llm", created_at=noon)
    _save_news(news_repo, title="カタログ記事2", source_name="Catalog Feed", source_label="ai_llm", created_at=noon)
    _save_news(news_repo, title="要約付き記事", source_name="Blog Feed", source_label="swe_general", created_at=noon)

    activity = collect_activity(
        day=_DAY, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo, news_repo=news_repo,
        settings=settings,
    )

    assert [item.title for item, _record in activity.news] == ["要約付き記事"]
    assert activity.catalog_news_counts == {"ai_llm": 2}


async def test_generate_daily_summary_skips_llm_call_when_activity_is_empty(tmp_path: Path) -> None:
    """活動が無い日はNoneを返し、LLM(フェイク)を呼ばず、DBにも保存しない."""
    paper_repo, todo_repo, memory_repo, news_repo, summary_repo = _make_repos(tmp_path)
    settings = _make_settings(tmp_path)
    summarizer = _FakeDailySummarizer()

    result = await generate_daily_summary(
        day=_DAY, summarizer=summarizer, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo,
        news_repo=news_repo, summary_repo=summary_repo, settings=settings,
    )

    assert result is None
    assert summarizer.received_prompts == []
    assert summary_repo.get_latest() is None


async def test_generate_daily_summary_saves_record_when_activity_exists(tmp_path: Path) -> None:
    """活動がある日はサマリーが生成・保存される."""
    paper_repo, todo_repo, memory_repo, news_repo, summary_repo = _make_repos(tmp_path)
    settings = _make_settings(tmp_path)
    noon = datetime(2026, 8, 30, 12, 0, tzinfo=_JST).astimezone(UTC)
    _save_paper(paper_repo, title="論文", created_at=noon)
    summarizer = _FakeDailySummarizer()

    result = await generate_daily_summary(
        day=_DAY, summarizer=summarizer, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo,
        news_repo=news_repo, summary_repo=summary_repo, settings=settings,
    )

    assert result is not None
    assert result.summary_date == _DAY
    assert len(summarizer.received_prompts) == 1
    assert "論文" in summarizer.received_prompts[0]
    saved = summary_repo.get_latest()
    assert saved is not None
    assert saved.content == result.content


def test_memory_theme_included_when_updated_in_range(tmp_path: Path) -> None:
    """当日updated_atのMemoryThemeが集計に含まれる."""
    paper_repo, todo_repo, memory_repo, news_repo, _summary_repo = _make_repos(tmp_path)
    settings = _make_settings(tmp_path)
    noon = datetime(2026, 8, 30, 12, 0, tzinfo=_JST).astimezone(UTC)
    memory_repo.upsert_theme(slug="test-theme", description="テストテーマの説明", updated_at=noon)

    activity = collect_activity(
        day=_DAY, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo, news_repo=news_repo,
        settings=settings,
    )

    assert [t.slug for t in activity.memory_themes] == ["test-theme"]
