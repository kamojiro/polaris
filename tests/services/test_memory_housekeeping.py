"""memory_housekeeping(記憶テーマ棚卸しオーケストレーション)の純ロジックテスト.

実LLMは使わず、フェイクの MemoryHousekeepingDetector を注入する
(tests/services/test_daily_summary.py と同じパターン)。
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from polaris.agent.memory_housekeeping import HousekeepingDetectionResult, HousekeepingSuggestionItem
from polaris.db.memory_housekeeping_repository import MemoryHousekeepingRepository
from polaris.db.memory_repository import MemoryRepository
from polaris.db.session import create_db_engine
from polaris.services.memory import write_theme_file
from polaris.services.memory_housekeeping import run_memory_housekeeping
from polaris.settings import MemorySettings, Settings


class _FakeMemoryHousekeepingDetector:
    """渡されたthemesをそのまま記録し、固定の結果を返すフェイク."""

    def __init__(self, result: HousekeepingDetectionResult) -> None:
        self._result = result
        self.received_themes: list[tuple[str, str, str]] = []

    async def detect(self, *, themes: Sequence[tuple[str, str, str]]) -> HousekeepingDetectionResult:
        self.received_themes = list(themes)
        return self._result


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(DB_PATH=str(tmp_path / "test.db"), memory=MemorySettings(dir=str(tmp_path / "memory")))


async def test_run_memory_housekeeping_saves_detected_suggestions(tmp_path: Path) -> None:
    """全テーマの現在の内容がdetectorに渡され、検出結果がDBに保存される."""
    settings = _make_settings(tmp_path)
    engine = create_db_engine(str(tmp_path / "test.db"))
    memory_repo = MemoryRepository(engine)
    housekeeping_repo = MemoryHousekeepingRepository(engine)

    now = datetime.now(UTC)
    memory_repo.upsert_theme(slug="theme-a", description="テーマA", updated_at=now)
    memory_repo.upsert_theme(slug="theme-b", description="テーマB", updated_at=now)
    write_theme_file("theme-a", "テーマAの内容", settings=settings)
    write_theme_file("theme-b", "テーマBの内容", settings=settings)

    detector = _FakeMemoryHousekeepingDetector(
        HousekeepingDetectionResult(
            suggestions=[
                HousekeepingSuggestionItem(
                    suggestion_type="merge", target_theme_slugs=["theme-a", "theme-b"], detail="内容が重複"
                )
            ]
        )
    )

    result = await run_memory_housekeeping(
        detector=detector, memory_repo=memory_repo, housekeeping_repo=housekeeping_repo, settings=settings
    )

    assert len(result) == 1
    assert result[0].suggestion_type == "merge"
    assert result[0].target_themes == "theme-a,theme-b"
    assert {slug for slug, _content, _updated_at in detector.received_themes} == {"theme-a", "theme-b"}

    saved = housekeeping_repo.list_latest()
    assert len(saved) == 1
    assert saved[0].detail == "内容が重複"


async def test_run_memory_housekeeping_with_no_themes_saves_nothing(tmp_path: Path) -> None:
    """テーマが1件も無くてもエラーにならず、空の結果を保存する(Edge Case)."""
    settings = _make_settings(tmp_path)
    engine = create_db_engine(str(tmp_path / "test.db"))
    memory_repo = MemoryRepository(engine)
    housekeeping_repo = MemoryHousekeepingRepository(engine)
    detector = _FakeMemoryHousekeepingDetector(HousekeepingDetectionResult(suggestions=[]))

    result = await run_memory_housekeeping(
        detector=detector, memory_repo=memory_repo, housekeeping_repo=housekeeping_repo, settings=settings
    )

    assert result == []
    assert housekeeping_repo.list_latest() == []


async def test_run_memory_housekeeping_clears_previous_suggestions_when_now_empty(tmp_path: Path) -> None:
    """前回バッチで候補があっても、今回0件ならDB上の候補も消える(FR-006)."""
    settings = _make_settings(tmp_path)
    engine = create_db_engine(str(tmp_path / "test.db"))
    memory_repo = MemoryRepository(engine)
    housekeeping_repo = MemoryHousekeepingRepository(engine)
    now = datetime.now(UTC)
    memory_repo.upsert_theme(slug="theme-a", description="テーマA", updated_at=now)
    write_theme_file("theme-a", "テーマAの内容", settings=settings)

    await run_memory_housekeeping(
        detector=_FakeMemoryHousekeepingDetector(
            HousekeepingDetectionResult(
                suggestions=[
                    HousekeepingSuggestionItem(suggestion_type="stale", target_theme_slugs=["theme-a"], detail="古い")
                ]
            )
        ),
        memory_repo=memory_repo,
        housekeeping_repo=housekeeping_repo,
        settings=settings,
    )
    assert len(housekeeping_repo.list_latest()) == 1

    await run_memory_housekeeping(
        detector=_FakeMemoryHousekeepingDetector(HousekeepingDetectionResult(suggestions=[])),
        memory_repo=memory_repo,
        housekeeping_repo=housekeeping_repo,
        settings=settings,
    )

    assert housekeeping_repo.list_latest() == []
