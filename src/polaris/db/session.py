"""DB エンジンの生成."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import SQLModel, create_engine

if TYPE_CHECKING:
    from sqlalchemy import Engine


def create_db_engine(db_path: str) -> Engine:
    """SQLite の Engine を作り、テーブルが無ければ作成して返す."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    return engine
