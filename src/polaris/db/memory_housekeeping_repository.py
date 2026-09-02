"""記憶テーマの定期棚卸し(MemoryHousekeepingSuggestion)の永続化リポジトリ(024-memory-theme-housekeeping).

`db/memory_repository.py`/`db/daily_summary_repository.py`と同じ「メソッドごとにSessionを開く」
パターンを踏襲する。テーブルは常に最新バッチの行のみを持つ(過去の検出結果は蓄積しない、FR-005)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, select

from polaris.domain.entities import MemoryHousekeepingSuggestion

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Engine


class MemoryHousekeepingRepository:
    """MemoryHousekeepingSuggestion の全置き換え保存・取得を担う."""

    def __init__(self, engine: Engine) -> None:
        """Engine を受け取って初期化する."""
        self._engine = engine

    def replace_all(self, suggestions: Sequence[MemoryHousekeepingSuggestion]) -> None:
        """既存の全行を削除してから、`suggestions`を挿入する(1トランザクション).

        `suggestions`が空でも削除は必ず行う(FR-006: 検出候補0件なら既存候補を消去する)。
        """
        with Session(self._engine, expire_on_commit=False) as session:
            for existing in session.exec(select(MemoryHousekeepingSuggestion)).all():
                session.delete(existing)
            for suggestion in suggestions:
                session.add(suggestion)
            session.commit()

    def list_latest(self) -> list[MemoryHousekeepingSuggestion]:
        """現在保存されている提案を全件返す(`generated_at`降順. テーブルは常に最新バッチのみ保持)."""
        with Session(self._engine, expire_on_commit=False) as session:
            query = select(MemoryHousekeepingSuggestion).order_by(
                MemoryHousekeepingSuggestion.generated_at.desc()  # type: ignore[union-attr]
            )
            return list(session.exec(query).all())
