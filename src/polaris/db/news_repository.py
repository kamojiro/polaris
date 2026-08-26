"""ニュース記事(Item + NewsRecord)の永続化リポジトリ(008-daily-digest-domain Phase A).

`db/repository.py`(PaperRepository)と同じ「メソッドごとに Session を開く」パターンを踏襲する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import Item, NewsRecord

if TYPE_CHECKING:
    from sqlalchemy import Engine


class NewsRepository:
    """Item + NewsRecord の保存・検索を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def find_by_source_url(self, source_url: str) -> tuple[Item, NewsRecord] | None:
        """source_url で既存レコードを検索する(重複防止に使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.exec(select(NewsRecord).where(NewsRecord.source_url == source_url)).first()
            if record is None:
                return None
            item = session.get(Item, record.item_id)
            if item is None:
                return None
            return item, record

    def save_news(self, item: Item, record: NewsRecord) -> None:
        """Item → NewsRecord の順で 1 トランザクションとして保存する(PaperRepository.save_paperと同型)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(item)
            session.add(record)
            session.commit()

    def list_news(self, *, limit_per_label: int | None = None) -> list[tuple[Item, NewsRecord]]:
        """保存済みのニュース記事を公開日時の降順で返す.

        `limit_per_label`はsource_labelごとの絞り込み件数(全体への単一LIMITではない)。
        情報源によって更新頻度が大きく異なる(例: Hacker Newsは1日に何度も更新される一方、
        arXivのタイムスタンプは投稿日単位)ため、全体にLIMITをかけると更新頻度の低い情報源が
        一覧から丸ごと消えてしまう。実際にarXivの取り込み件数を増やした際にこの問題が発生し、
        修正した(2026-08-27)。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            query = (
                select(Item, NewsRecord)
                .join(NewsRecord, NewsRecord.item_id == Item.id)  # type: ignore[arg-type]
                .order_by(NewsRecord.published_at.desc())  # type: ignore[union-attr]
            )
            rows = list(session.exec(query).all())

        if limit_per_label is None:
            return rows

        counts: dict[str, int] = {}
        result: list[tuple[Item, NewsRecord]] = []
        for item, record in rows:
            count = counts.get(record.source_label, 0)
            if count >= limit_per_label:
                continue
            counts[record.source_label] = count + 1
            result.append((item, record))
        return result
