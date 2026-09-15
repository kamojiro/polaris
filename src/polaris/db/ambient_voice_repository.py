"""常時音声認識(026-voice-input Stage2代替案)の永続化リポジトリ.

`db/paper_research_repository.py`と同じ「メソッドごとにSessionを開く」パターン・
status列キュー(`status`: "pending" → "in_progress" → "done"/"failed")を踏襲する。
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import AmbientVoiceChunkRecord

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine

_STATUS_PENDING = "pending"
_STATUS_IN_PROGRESS = "in_progress"
_STATUS_DONE = "done"
_STATUS_FAILED = "failed"


class AmbientVoiceRepository:
    """AmbientVoiceChunkRecord(常時音声認識チャンクのキュー)の保存・状態遷移・取得を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def save(self, record: AmbientVoiceChunkRecord) -> None:
        """新規のチャンクを1件保存する(クライアントのフラッシュ経路が呼ぶ、常にpendingで作る想定)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(record)
            session.commit()

    def reclaim_stale(self, *, now: datetime, older_than_minutes: int, max_attempts: int) -> int:
        """クラッシュ等で`in_progress`のまま放置された行を回収する(`paper_research_repository`と同じ方針)."""
        cutoff = now - timedelta(minutes=older_than_minutes)
        changed = 0
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(AmbientVoiceChunkRecord).where(
                AmbientVoiceChunkRecord.status == _STATUS_IN_PROGRESS,
                AmbientVoiceChunkRecord.started_at < cutoff,  # type: ignore[operator]
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
        """`reclaim_stale`対象にならない(=まだ生きている)`in_progress`行があるか調べる(多重起動ガード)."""
        cutoff = now - timedelta(minutes=older_than_minutes)
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(AmbientVoiceChunkRecord).where(
                AmbientVoiceChunkRecord.status == _STATUS_IN_PROGRESS,
                AmbientVoiceChunkRecord.started_at >= cutoff,  # type: ignore[operator]
            )
            return session.exec(query).first() is not None

    def claim_next_pending(self, *, now: datetime) -> AmbientVoiceChunkRecord | None:
        """最古の`pending`行を1件`in_progress`にして返す(無ければNone)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(AmbientVoiceChunkRecord)
                .where(AmbientVoiceChunkRecord.status == _STATUS_PENDING)
                .order_by(AmbientVoiceChunkRecord.created_at.asc())  # type: ignore[union-attr]
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

    def mark_done(self, record_id: str, *, worth_reacting: bool, comment: str | None, completed_at: datetime) -> None:
        """判定結果を完了として記録する."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.get(AmbientVoiceChunkRecord, record_id)
            if record is None:
                return
            record.status = _STATUS_DONE
            record.worth_reacting = worth_reacting
            record.comment = comment
            record.completed_at = completed_at
            session.add(record)
            session.commit()

    def mark_failed(self, record_id: str, *, error: str, completed_at: datetime) -> None:
        """判定処理の失敗を記録する(1チャンクの失敗はバッチ全体を落とさない、呼び出し側の責務)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.get(AmbientVoiceChunkRecord, record_id)
            if record is None:
                return
            record.status = _STATUS_FAILED
            record.error = error
            record.completed_at = completed_at
            session.add(record)
            session.commit()

    def get_latest_done_comment(self) -> str | None:
        """直近に完了したチャンクの`comment`を返す(話題の継続性をLLMに緩く判断させるための材料、無ければNone)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(AmbientVoiceChunkRecord)
                .where(AmbientVoiceChunkRecord.status == _STATUS_DONE)
                .order_by(AmbientVoiceChunkRecord.completed_at.desc())  # type: ignore[union-attr]
            )
            record = session.exec(query).first()
            return record.comment if record is not None else None

    def get_latest_reaction(self) -> AmbientVoiceChunkRecord | None:
        """直近の`worth_reacting=True`行を返す(通知バナー用)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(AmbientVoiceChunkRecord)
                .where(AmbientVoiceChunkRecord.worth_reacting == True)  # noqa: E712
                .order_by(AmbientVoiceChunkRecord.completed_at.desc())  # type: ignore[union-attr]
            )
            return session.exec(query).first()
