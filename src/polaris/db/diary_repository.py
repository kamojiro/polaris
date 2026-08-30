"""日記ドメイン(Item + DiaryRecord + DiaryEvent)の永続化リポジトリ(019-diary-domain).

`db/memory_repository.py`と同じ「メソッドごとにSessionを開く」パターンを踏襲する。
`DiaryRecord`は(`MemoryTheme`/`DailySummaryRecord`と異なり)`Item`ハブを経由する
(`domain/entities.py`のDiaryRecordのdocstring参照)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import DiaryEvent, DiaryRecord, Item

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy import Engine


class DiaryRepository:
    """Item + DiaryRecord(現在状態層)・DiaryEvent(ログ層)の保存・検索を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def append_event(self, event: DiaryEvent) -> None:
        """ログ層に1件追記する(追記のみ、更新・削除はしない)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(event)
            session.commit()

    def list_events(self, entry_date: date) -> list[DiaryEvent]:
        """指定日のログを古い順(recorded_at昇順)で返す(現在状態の書き直しに使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(DiaryEvent)
                .where(DiaryEvent.entry_date == entry_date)
                .order_by(DiaryEvent.recorded_at.asc())  # type: ignore[union-attr]
            )
            return list(session.exec(query).all())

    def get_record(self, entry_date: date) -> DiaryRecord | None:
        """指定日の現在状態(DiaryRecord)を返す(無ければNone)."""
        with Session(self._engine, expire_on_commit=False) as session:
            return session.exec(select(DiaryRecord).where(DiaryRecord.entry_date == entry_date)).first()

    def upsert_record(self, item: Item, record: DiaryRecord) -> None:
        """`entry_date`でupsertする.

        1日目はItem+DiaryRecordを新規作成する。2回目以降は、日記本文が1日のうちに何度も
        更新されうる(`spec.md`のUser Story 2)ため、DiaryRecordだけでなくItem.title/summaryも
        更新する(Item.summaryが初回の内容のまま古くならないようにするため)。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            existing = session.exec(
                select(DiaryRecord).where(DiaryRecord.entry_date == record.entry_date)
            ).first()
            if existing is None:
                session.add(item)
                session.add(record)
            else:
                existing.content = record.content
                existing.updated_at = record.updated_at
                session.add(existing)
                existing_item = session.get(Item, existing.item_id)
                if existing_item is not None:
                    existing_item.title = item.title
                    existing_item.summary = item.summary
                    session.add(existing_item)
            session.commit()

    def list_records_in_range(self, start_date: date, end_date: date) -> list[DiaryRecord]:
        """`entry_date`が`[start_date, end_date]`(両端含む)に入るDiaryRecordをentry_date昇順で返す(User Story 5)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(DiaryRecord)
                .where(DiaryRecord.entry_date >= start_date, DiaryRecord.entry_date <= end_date)  # type: ignore[operator]
                .order_by(DiaryRecord.entry_date.asc())  # type: ignore[union-attr]
            )
            return list(session.exec(query).all())

    def get_latest_updated_record(self) -> DiaryRecord | None:
        """`updated_at`降順の先頭(直近で書かれたエントリ)を返す(無ければNone、User Story 6のアンカー)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(DiaryRecord).order_by(DiaryRecord.updated_at.desc())  # type: ignore[union-attr]
            return session.exec(query).first()

    def list_records_before(self, entry_date: date, *, limit: int) -> list[DiaryRecord]:
        """`entry_date`未満のDiaryRecordをentry_date降順で`limit`件返す(User Story 6のアンカー前後文脈)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(DiaryRecord)
                .where(DiaryRecord.entry_date < entry_date)  # type: ignore[operator]
                .order_by(DiaryRecord.entry_date.desc())  # type: ignore[union-attr]
                .limit(limit)
            )
            return list(session.exec(query).all())
