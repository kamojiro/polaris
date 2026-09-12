"""関連論文調査(027-related-paper-research)の永続化リポジトリ.

`db/memory_housekeeping_repository.py`と同じ「メソッドごとにSessionを開く」パターンを
踏襲する。`PaperResearchRepository`はこのコードベース初のstatus列キュー
(`status`: "pending" → "in_progress" → "done"/"failed")で、`claim_next_pending`/
`reclaim_stale`が状態遷移を担う。Celery/RQ等の本格タスクキューは使わず(008で
APScheduler常駐を見送ったのと同じ判断)、DBの`status`カラムだけで素朴に実装する。
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import (
    PaperDeepAnalysisRecord,
    PaperResearchDiscoveredPaper,
    PaperResearchRecord,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine

_STATUS_PENDING = "pending"
_STATUS_IN_PROGRESS = "in_progress"
_STATUS_DONE = "done"
_STATUS_FAILED = "failed"
_ACTIVE_STATUSES = (_STATUS_PENDING, _STATUS_IN_PROGRESS)


class PaperResearchRepository:
    """PaperResearchRecord(調査依頼のキュー)の保存・状態遷移・取得を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def save(self, record: PaperResearchRecord) -> None:
        """新規の調査依頼を1件保存する(受付ツールが呼ぶ、常にpendingで作る想定)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(record)
            session.commit()

    def find_active_by_seed(self, seed_item_id: str) -> PaperResearchRecord | None:
        """指定論文を起点とする未完了の調査(pending/in_progress)があれば返す(重複受付防止)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(PaperResearchRecord).where(
                PaperResearchRecord.seed_item_id == seed_item_id,
                PaperResearchRecord.status.in_(_ACTIVE_STATUSES),  # type: ignore[attr-defined]
            )
            return session.exec(query).first()

    def reclaim_stale(self, *, now: datetime, older_than_minutes: int, max_attempts: int) -> int:
        """クラッシュ等で`in_progress`のまま放置された行を回収する.

        `started_at`が`older_than_minutes`より前の`in_progress`行を対象に、
        `attempts`が`max_attempts`未満なら`pending`へ戻して再試行させ、上限に
        達していれば`failed`にする(無限リトライを防ぐ)。CLI実行のたびに最初に
        呼ぶ想定。戻り値は変更した件数。
        """
        cutoff = now - timedelta(minutes=older_than_minutes)
        changed = 0
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(PaperResearchRecord).where(
                PaperResearchRecord.status == _STATUS_IN_PROGRESS,
                PaperResearchRecord.started_at < cutoff,  # type: ignore[operator]
            )
            for record in session.exec(query).all():
                if record.attempts < max_attempts:
                    record.status = _STATUS_PENDING
                else:
                    record.status = _STATUS_FAILED
                    record.error = "処理中にクラッシュしたまま試行回数の上限に達しました"
                    record.completed_at = now
                session.add(record)
                changed += 1
            session.commit()
        return changed

    def has_fresh_in_progress(self, *, now: datetime, older_than_minutes: int) -> bool:
        """`reclaim_stale`対象にならない(=まだ生きている)`in_progress`行があるか調べる.

        cron間隔が1回の実行時間より短い場合の多重起動ガードに使う。
        """
        cutoff = now - timedelta(minutes=older_than_minutes)
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(PaperResearchRecord).where(
                PaperResearchRecord.status == _STATUS_IN_PROGRESS,
                PaperResearchRecord.started_at >= cutoff,  # type: ignore[operator]
            )
            return session.exec(query).first() is not None

    def claim_next_pending(self, *, now: datetime) -> PaperResearchRecord | None:
        """最古の`pending`行を1件`in_progress`にして返す(無ければNone).

        同一トランザクション内で状態更新までコミットする(claim = 状態変更)。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(PaperResearchRecord)
                .where(PaperResearchRecord.status == _STATUS_PENDING)
                .order_by(PaperResearchRecord.created_at.asc())  # type: ignore[union-attr]
            )
            record = session.exec(query).first()
            if record is None:
                return None
            record.status = _STATUS_IN_PROGRESS
            record.started_at = now
            record.attempts += 1
            session.add(record)
            session.commit()
            return record

    def mark_done(self, record_id: str, *, result_summary: str, completed_at: datetime) -> None:
        """調査を完了として記録する."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.get(PaperResearchRecord, record_id)
            if record is None:
                return
            record.status = _STATUS_DONE
            record.result_summary = result_summary
            record.completed_at = completed_at
            session.add(record)
            session.commit()

    def mark_failed(self, record_id: str, *, error: str, completed_at: datetime) -> None:
        """調査を失敗として記録する(1レコードの失敗はバッチ全体を落とさない、呼び出し側の責務)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.get(PaperResearchRecord, record_id)
            if record is None:
                return
            record.status = _STATUS_FAILED
            record.error = error
            record.completed_at = completed_at
            session.add(record)
            session.commit()

    def get_latest_done(self) -> PaperResearchRecord | None:
        """直近に完了した調査を返す(`GET /api/paper-research/latest`用)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(PaperResearchRecord)
                .where(PaperResearchRecord.status == _STATUS_DONE)
                .order_by(PaperResearchRecord.completed_at.desc())  # type: ignore[union-attr]
            )
            return session.exec(query).first()


class PaperDeepAnalysisRepository:
    """PaperDeepAnalysisRecord(精読結果のキャッシュ)の保存・取得を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def save(self, record: PaperDeepAnalysisRecord) -> None:
        """精読結果を`item_id`でupsertする(既存があれば置き換える)."""
        with Session(self._engine, expire_on_commit=False) as session:
            existing = session.exec(
                select(PaperDeepAnalysisRecord).where(PaperDeepAnalysisRecord.item_id == record.item_id)
            ).first()
            if existing is not None:
                session.delete(existing)
                session.commit()
            session.add(record)
            session.commit()

    def find_by_item_id(self, item_id: str) -> PaperDeepAnalysisRecord | None:
        """指定論文の精読結果があれば返す(あれば再抽出・再取り込みをスキップする)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(PaperDeepAnalysisRecord).where(PaperDeepAnalysisRecord.item_id == item_id)
            return session.exec(query).first()


class PaperResearchDiscoveredRepository:
    """PaperResearchDiscoveredPaper(調査が自動取り込みした論文の出自)の保存・取得を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def save(self, record: PaperResearchDiscoveredPaper) -> None:
        """出自を記録する(`item_id`に既存行があれば何もしない、最初に発見した調査を残す)."""
        with Session(self._engine, expire_on_commit=False) as session:
            existing = session.exec(
                select(PaperResearchDiscoveredPaper).where(PaperResearchDiscoveredPaper.item_id == record.item_id)
            ).first()
            if existing is not None:
                return
            session.add(record)
            session.commit()

    def delete_by_item_id(self, item_id: str) -> None:
        """出自を削除する(ユーザーが後から`save_paper`で明示的に保存した場合、ライブラリの一員に昇格させる)."""
        with Session(self._engine, expire_on_commit=False) as session:
            existing = session.exec(
                select(PaperResearchDiscoveredPaper).where(PaperResearchDiscoveredPaper.item_id == item_id)
            ).first()
            if existing is not None:
                session.delete(existing)
                session.commit()

    def list_item_ids(self) -> list[str]:
        """出自のある(=調査で自動取り込みされた)論文の`item_id`一覧を返す."""
        with Session(self._engine, expire_on_commit=False) as session:
            rows = session.exec(select(PaperResearchDiscoveredPaper.item_id)).all()
            return list(rows)
