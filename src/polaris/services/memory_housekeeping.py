"""記憶テーマの定期棚卸し(024-memory-theme-housekeeping)のオーケストレーション.

`023-daily-summary-notification`と同じく、チャットのターンに紐づかない独立バックグラウンド処理
(`docs/adr/0003-chat-turn-pipeline.md`が定義した前処理/メイン/後処理の3段パイプラインの対象外)。
`cli/run_memory_housekeeping.py`から呼ばれる想定。全テーマの現在の内容を読み直すだけで、
`memory/<slug>.md`・`MemoryEvent`ログには一切書き込まない(v1は検出・表示のみ)。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from polaris.domain.entities import MemoryHousekeepingSuggestion
from polaris.services.memory import read_theme_file

if TYPE_CHECKING:
    from polaris.agent.memory_housekeeping import MemoryHousekeepingDetector
    from polaris.db.memory_housekeeping_repository import MemoryHousekeepingRepository
    from polaris.db.memory_repository import MemoryRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

__all__ = ["run_memory_housekeeping"]


async def run_memory_housekeeping(
    *,
    detector: MemoryHousekeepingDetector,
    memory_repo: MemoryRepository,
    housekeeping_repo: MemoryHousekeepingRepository,
    settings: Settings,
) -> list[MemoryHousekeepingSuggestion]:
    """全記憶テーマの現在の内容を読み、整理候補を検出して保存する(テーマ0〜1件でもエラーにしない).

    検出結果が0件でも`housekeeping_repo.replace_all`は必ず呼ぶ(FR-006: 既存候補があれば消去する)。
    """
    themes = memory_repo.list_themes()
    theme_contents = [
        (theme.slug, content, theme.updated_at.isoformat())
        for theme in themes
        if (content := read_theme_file(theme.slug, settings=settings)) is not None
    ]

    result = await detector.detect(themes=theme_contents)

    generated_at = datetime.now(UTC)
    suggestions = [
        MemoryHousekeepingSuggestion(
            id=uuid.uuid4().hex,
            suggestion_type=item.suggestion_type,
            target_themes=",".join(item.target_theme_slugs),
            detail=item.detail,
            generated_at=generated_at,
        )
        for item in result.suggestions
    ]
    housekeeping_repo.replace_all(suggestions)
    logger.info("記憶テーマ棚卸し完了: themes=%d, suggestions=%d", len(theme_contents), len(suggestions))
    return suggestions
