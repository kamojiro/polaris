"""日次サマリー(DailySummaryRecord)の永続化リポジトリ(023-daily-summary-notification).

`db/memory_repository.py`と同じく`Item`ハブは経由しない(特定の知識アイテム1件に
紐づくものではなく、複数ドメインを横断した1日分のまとめのため)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import DailySummaryRecord

if TYPE_CHECKING:
    from sqlalchemy import Engine


class DailySummaryRepository:
    """DailySummaryRecord の保存・検索を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def save(self, record: DailySummaryRecord) -> None:
        """`summary_date`でupsertする(同じ日にCLIを再実行したら上書きする、冪等性のため)."""
        with Session(self._engine, expire_on_commit=False) as session:
            existing = session.exec(
                select(DailySummaryRecord).where(DailySummaryRecord.summary_date == record.summary_date)
            ).first()
            if existing is None:
                session.add(record)
            else:
                existing.content = record.content
                existing.generated_at = record.generated_at
                session.add(existing)
            session.commit()

    def get_latest(self) -> DailySummaryRecord | None:
        """最新(summary_date降順の先頭)のサマリーを返す(フロントのバナー取得用)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(DailySummaryRecord).order_by(DailySummaryRecord.summary_date.desc())  # type: ignore[union-attr]
            return session.exec(query).first()
