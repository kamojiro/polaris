"""1日分の活動を横断集計し、LLMで要約する(023-daily-summary-notification).

チャットのターンに紐づかない初めての処理(`docs/adr/0003-chat-turn-pipeline.md`が
定義した前処理/メイン/後処理の3段パイプラインの対象外)。`cli/generate_daily_summary.py`
から1日1回呼ばれる想定。

`013-ir-analysis-domain`は未実装のため集計対象に含めない。実装され次第、
`collect_activity`にブロックを1つ足すだけで済む構造にしてある。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

from polaris.domain.entities import DailySummaryRecord

if TYPE_CHECKING:
    from datetime import date

    from polaris.agent.daily_summary import DailySummarizer
    from polaris.db.daily_summary_repository import DailySummaryRepository
    from polaris.db.memory_repository import MemoryRepository
    from polaris.db.news_repository import NewsRepository
    from polaris.db.repository import PaperRepository
    from polaris.db.todo_repository import TodoRepository
    from polaris.domain.entities import Item, MemoryTheme, NewsRecord, PaperRecord, TodoRecord
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

__all__ = ["DailyActivity", "collect_activity", "generate_daily_summary", "local_day_bounds_utc"]


def local_day_bounds_utc(day: date, *, tz_name: str) -> tuple[datetime, datetime]:
    """`day`(指定タイムゾーンでの暦日)の`[00:00, 翌00:00)`をUTCの`datetime`ペアに変換する.

    DB保存値はすべて`datetime.now(UTC)`(`services/ingest_paper.py`他)だが、
    「1日のまとめ」は生活時間の区切りであるべきという判断(spec未決定事項の確定、2026-08-30)。
    """
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)  # 翌日0時ちょうど(排他的な上限)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


class DailyActivity(NamedTuple):
    """1日分の集計結果(LLMに渡す前の素材)."""

    papers: list[tuple[Item, PaperRecord]]
    todos_added: list[tuple[Item, TodoRecord]]
    todos_completed: list[tuple[Item, TodoRecord]]
    memory_themes: list[MemoryTheme]
    news: list[tuple[Item, NewsRecord]]  # 要約付きフィードのみ(カタログ系は除く)
    catalog_news_counts: dict[str, int]  # カタログ系(skip_summary=True)の source_label -> 件数

    def is_empty(self) -> bool:
        """全ドメインで活動が無いか(この場合サマリー自体を生成しない)."""
        return not (
            self.papers
            or self.todos_added
            or self.todos_completed
            or self.memory_themes
            or self.news
            or self.catalog_news_counts
        )


def collect_activity(
    *,
    day: date,
    paper_repo: PaperRepository,
    todo_repo: TodoRepository,
    memory_repo: MemoryRepository,
    news_repo: NewsRepository,
    settings: Settings,
) -> DailyActivity:
    """`day`(設定のタイムゾーン基準の暦日)1日分の活動を各リポジトリから集計する."""
    start, end = local_day_bounds_utc(day, tz_name=settings.daily_summary.timezone)

    todos_added = todo_repo.list_todos_created_between(start, end)
    todos_completed = todo_repo.list_todos_completed_between(start, end)

    # カタログ系(skip_summary=True)フィードのnameを設定から引く(設定が唯一の真実、
    # services/ingest_news.pyと同じ考え方)。記事単位で再判定しない。
    catalog_feed_names = {feed.name for feed in settings.news.feeds if feed.skip_summary}
    all_news = news_repo.list_news_created_between(start, end)
    news = [(item, record) for item, record in all_news if record.source_name not in catalog_feed_names]
    catalog_news_counts: dict[str, int] = {}
    for _item, record in all_news:
        if record.source_name in catalog_feed_names:
            catalog_news_counts[record.source_label] = catalog_news_counts.get(record.source_label, 0) + 1

    return DailyActivity(
        papers=paper_repo.list_papers_created_between(start, end),
        todos_added=todos_added,
        todos_completed=todos_completed,
        memory_themes=memory_repo.list_themes_updated_between(start, end),
        news=news,
        catalog_news_counts=catalog_news_counts,
    )


def build_summary_prompt(activity: DailyActivity) -> str:
    """LLMに渡す活動ログのプロンプトを組み立てる.

    論文は`Item.title` + `Item.summary`(既に生成済みの要約)のみを渡す。本文全文は渡さない
    (`specs/IDEAS.md`に記録したコンテキスト肥大の問題と同じ轍を踏まないため)。
    """
    lines: list[str] = []

    if activity.papers:
        lines.append("## 保存した論文")
        lines.extend(f"- {item.title}: {item.summary}" for item, _record in activity.papers)

    if activity.todos_added:
        lines.append("## 追加したTODO")
        lines.extend(f"- {item.title}" for item, _record in activity.todos_added)

    if activity.todos_completed:
        lines.append("## 完了したTODO")
        lines.extend(f"- {item.title}" for item, _record in activity.todos_completed)

    if activity.memory_themes:
        lines.append("## 更新された記憶のテーマ")
        lines.extend(f"- {theme.slug}: {theme.description}" for theme in activity.memory_themes)

    if activity.news:
        lines.append("## 読んだニュース記事")
        lines.extend(f"- {item.title}: {item.summary}" for item, _record in activity.news)

    if activity.catalog_news_counts:
        lines.append("## その他取り込んだ記事(タイトルのみのカタログ表示)")
        lines.extend(f"- {label}: {count}件" for label, count in activity.catalog_news_counts.items())

    return "\n".join(lines)


async def generate_daily_summary(
    *,
    day: date,
    summarizer: DailySummarizer,
    paper_repo: PaperRepository,
    todo_repo: TodoRepository,
    memory_repo: MemoryRepository,
    news_repo: NewsRepository,
    summary_repo: DailySummaryRepository,
    settings: Settings,
) -> DailySummaryRecord | None:
    """`day`分の活動を集計・要約し、保存する。活動が無い日は何もせず`None`を返す."""
    activity = collect_activity(
        day=day, paper_repo=paper_repo, todo_repo=todo_repo, memory_repo=memory_repo, news_repo=news_repo,
        settings=settings,
    )
    if activity.is_empty():
        logger.info("日次サマリー: %sは活動が無いためスキップします", day)
        return None

    content = await summarizer.summarize(build_summary_prompt(activity))
    record = DailySummaryRecord(
        id=uuid.uuid4().hex,
        summary_date=day,
        content=content,
        generated_at=datetime.now(UTC),
    )
    summary_repo.save(record)
    logger.info("日次サマリー生成完了: date=%s", day)
    return record
