"""チャット長期記憶(Item非依存、MemoryTheme + MemoryEvent)の永続化リポジトリ(017-chat-memory).

`db/todo_repository.py`と同じ「メソッドごとにSessionを開く」パターンを踏襲する。
論文・TODOと違い`Item`ハブは経由しない(記憶はチャット全体の横断的な仕組みで、
特定の知識アイテム1件に紐づくものではないため)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import MemoryEvent, MemoryTheme

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine


class MemoryRepository:
    """MemoryTheme(索引)・MemoryEvent(ログ層)の保存・検索を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def list_themes(self) -> list[MemoryTheme]:
        """テーマ索引を全件返す(想起・抽出のLLM呼び出しに渡す一覧)."""
        with Session(self._engine, expire_on_commit=False) as session:
            return list(session.exec(select(MemoryTheme)).all())

    def list_themes_updated_between(self, start: datetime, end: datetime) -> list[MemoryTheme]:
        """`updated_at`が`[start, end)`(UTC)に入るテーマ索引を返す(023-daily-summary-notification)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(MemoryTheme).where(MemoryTheme.updated_at >= start, MemoryTheme.updated_at < end)  # type: ignore[operator]
            return list(session.exec(query).all())

    def upsert_theme(self, *, slug: str, description: str, updated_at: datetime) -> None:
        """テーマ索引を作成、または既存テーマの説明・更新日時を上書きする."""
        with Session(self._engine, expire_on_commit=False) as session:
            existing = session.get(MemoryTheme, slug)
            if existing is None:
                session.add(MemoryTheme(slug=slug, description=description, updated_at=updated_at))
            else:
                existing.description = description
                existing.updated_at = updated_at
                session.add(existing)
            session.commit()

    def append_event(self, event: MemoryEvent) -> None:
        """ログ層に1件追記する(追記のみ、更新・削除はしない)."""
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(event)
            session.commit()

    def list_events(self, theme: str) -> list[MemoryEvent]:
        """指定テーマのログを古い順(extracted_at昇順)で返す(現在状態ファイルの書き直しに使う)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(MemoryEvent).where(MemoryEvent.theme == theme).order_by(MemoryEvent.extracted_at.asc())  # type: ignore[union-attr]
            return list(session.exec(query).all())
