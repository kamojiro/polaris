"""PaperResearchRepository/PaperDeepAnalysisRepository/PaperResearchDiscoveredRepository のテスト(一時SQLite使用)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polaris.db.paper_research_repository import (
    PaperDeepAnalysisRepository,
    PaperResearchDiscoveredRepository,
    PaperResearchRepository,
)
from polaris.db.session import create_db_engine
from polaris.domain.entities import (
    PaperDeepAnalysisRecord,
    PaperResearchDiscoveredPaper,
    PaperResearchRecord,
)

_NOW = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)


def _make_record(
    record_id: str = "res-1",
    *,
    seed_item_id: str = "item-1",
    status: str = "pending",
    attempts: int = 0,
    created_at: datetime = _NOW,
    started_at: datetime | None = None,
) -> PaperResearchRecord:
    return PaperResearchRecord(
        id=record_id,
        seed_item_id=seed_item_id,
        seed_title="Attention Is All You Need",
        status=status,
        attempts=attempts,
        created_at=created_at,
        started_at=started_at,
    )


def test_claim_next_pending_picks_oldest_and_marks_in_progress(tmp_path: Path) -> None:
    """最古のpending行を1件claimし、in_progressへ遷移してattemptsを増やす."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("res-old", created_at=_NOW))
    repo.save(_make_record("res-new", created_at=_NOW + timedelta(minutes=5)))

    claimed = repo.claim_next_pending(now=_NOW + timedelta(hours=1))

    assert claimed is not None
    assert claimed.id == "res-old"
    assert claimed.status == "in_progress"
    assert claimed.attempts == 1


def test_claim_next_pending_returns_none_when_empty(tmp_path: Path) -> None:
    """pending行が無ければNoneを返す."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.claim_next_pending(now=_NOW) is None


def test_reclaim_stale_returns_to_pending_within_attempt_limit(tmp_path: Path) -> None:
    """試行回数が上限未満のstale in_progressはpendingへ戻る."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=1, started_at=_NOW))

    changed = repo.reclaim_stale(now=_NOW + timedelta(hours=3), older_than_minutes=120, max_attempts=2)

    assert changed == 1
    reclaimed = repo.find_active_by_seed("item-1")
    assert reclaimed is not None
    assert reclaimed.status == "pending"


def test_reclaim_stale_marks_failed_when_attempts_exhausted(tmp_path: Path) -> None:
    """試行回数が上限に達しているstale in_progressはfailedになる."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=2, started_at=_NOW))

    changed = repo.reclaim_stale(now=_NOW + timedelta(hours=3), older_than_minutes=120, max_attempts=2)

    assert changed == 1
    assert repo.find_active_by_seed("item-1") is None  # failedはactiveではない


def test_reclaim_stale_ignores_fresh_in_progress(tmp_path: Path) -> None:
    """開始間もないin_progressは回収対象にならない."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=1, started_at=_NOW))

    changed = repo.reclaim_stale(now=_NOW + timedelta(minutes=5), older_than_minutes=120, max_attempts=2)

    assert changed == 0


def test_has_fresh_in_progress(tmp_path: Path) -> None:
    """開始間もないin_progressがあればTrue、stale化していればFalse."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress", attempts=1, started_at=_NOW))

    assert repo.has_fresh_in_progress(now=_NOW + timedelta(minutes=5), older_than_minutes=120) is True
    assert repo.has_fresh_in_progress(now=_NOW + timedelta(hours=3), older_than_minutes=120) is False


def test_find_active_by_seed_excludes_done_and_failed(tmp_path: Path) -> None:
    """完了済み・失敗済みの調査は「未完了」に含まれない(重複受付防止のため)."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("res-done", status="done"))

    assert repo.find_active_by_seed("item-1") is None


def test_mark_done_sets_result_and_status(tmp_path: Path) -> None:
    """mark_doneでstatus/result_summary/completed_atが更新される."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress"))

    repo.mark_done("res-1", result_summary="統合結果の本文", completed_at=_NOW)

    latest = repo.get_latest_done()
    assert latest is not None
    assert latest.result_summary == "統合結果の本文"


def test_mark_failed_sets_error_and_status(tmp_path: Path) -> None:
    """mark_failedでstatus/errorが更新され、get_latest_doneには出てこない."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record(status="in_progress"))

    repo.mark_failed("res-1", error="Semantic Scholar呼び出し失敗", completed_at=_NOW)

    assert repo.get_latest_done() is None


def test_get_latest_done_returns_most_recently_completed(tmp_path: Path) -> None:
    """完了済みが複数あれば最新のものを返す."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("res-old", seed_item_id="item-a", status="in_progress"))
    repo.save(_make_record("res-new", seed_item_id="item-b", status="in_progress"))
    repo.mark_done("res-old", result_summary="古い方", completed_at=_NOW)
    repo.mark_done("res-new", result_summary="新しい方", completed_at=_NOW + timedelta(hours=1))

    latest = repo.get_latest_done()

    assert latest is not None
    assert latest.id == "res-new"


def test_list_done_returns_newest_first_and_excludes_pending_or_failed(tmp_path: Path) -> None:
    """一覧表示は完了済みだけを完了日時の降順で返す(未完了・失敗は含まない)."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(_make_record("res-old", seed_item_id="item-a", status="in_progress"))
    repo.save(_make_record("res-new", seed_item_id="item-b", status="in_progress"))
    repo.save(_make_record("res-pending", seed_item_id="item-c"))
    repo.save(_make_record("res-failed", seed_item_id="item-d", status="in_progress"))
    repo.mark_done("res-old", result_summary="古い方", completed_at=_NOW)
    repo.mark_done("res-new", result_summary="新しい方", completed_at=_NOW + timedelta(hours=1))
    repo.mark_failed("res-failed", error="失敗", completed_at=_NOW + timedelta(hours=2))

    done = repo.list_done()

    assert [record.id for record in done] == ["res-new", "res-old"]


def test_list_done_respects_limit(tmp_path: Path) -> None:
    """limitを指定すると、新しい順に指定件数だけ返る."""
    repo = PaperResearchRepository(create_db_engine(str(tmp_path / "test.db")))
    for i in range(3):
        repo.save(_make_record(f"res-{i}", seed_item_id=f"item-{i}", status="in_progress"))
        repo.mark_done(f"res-{i}", result_summary=f"結果{i}", completed_at=_NOW + timedelta(hours=i))

    done = repo.list_done(limit=2)

    assert [record.id for record in done] == ["res-2", "res-1"]


def test_deep_analysis_upsert_by_item_id(tmp_path: Path) -> None:
    """PaperDeepAnalysisRepository.saveはitem_idでupsertする(既存を置き換える)."""
    repo = PaperDeepAnalysisRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(
        PaperDeepAnalysisRecord(id="a1", item_id="item-x", problem="旧課題", solution="旧解決", created_at=_NOW)
    )

    repo.save(
        PaperDeepAnalysisRecord(id="a2", item_id="item-x", problem="新課題", solution="新解決", created_at=_NOW)
    )

    found = repo.find_by_item_id("item-x")
    assert found is not None
    assert found.problem == "新課題"


def test_deep_analysis_find_by_item_id_returns_none_when_missing(tmp_path: Path) -> None:
    """未精読の論文はNoneを返す(精読・LLM抽出をスキップする判定に使う)."""
    repo = PaperDeepAnalysisRepository(create_db_engine(str(tmp_path / "test.db")))

    assert repo.find_by_item_id("item-unknown") is None


def test_discovered_save_keeps_first_record_on_rediscovery(tmp_path: Path) -> None:
    """同じ論文が別の調査で再発見されても、最初に発見した調査の記録が残る."""
    repo = PaperResearchDiscoveredRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(
        PaperResearchDiscoveredPaper(
            id="d1", item_id="item-y", research_id="research-first", discovered_at=_NOW
        )
    )

    repo.save(
        PaperResearchDiscoveredPaper(
            id="d2", item_id="item-y", research_id="research-second", discovered_at=_NOW + timedelta(days=1)
        )
    )

    assert repo.list_item_ids() == ["item-y"]


def test_discovered_delete_by_item_id(tmp_path: Path) -> None:
    """ユーザーが後からsave_paperした論文は出自を削除できる(ライブラリの一員に昇格)."""
    repo = PaperResearchDiscoveredRepository(create_db_engine(str(tmp_path / "test.db")))
    repo.save(PaperResearchDiscoveredPaper(id="d1", item_id="item-z", research_id="research-1", discovered_at=_NOW))

    repo.delete_by_item_id("item-z")

    assert repo.list_item_ids() == []


def test_discovered_delete_by_item_id_missing_is_noop(tmp_path: Path) -> None:
    """存在しないitem_idの削除は何もしない(エラーにならない)."""
    repo = PaperResearchDiscoveredRepository(create_db_engine(str(tmp_path / "test.db")))

    repo.delete_by_item_id("item-does-not-exist")  # 例外を送出しないことを確認

    assert repo.list_item_ids() == []
