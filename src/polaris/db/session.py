"""DB エンジンの生成."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import SQLModel, create_engine

from polaris.db.vector_store import create_vector_table, register_vec_extension

if TYPE_CHECKING:
    from sqlalchemy import Engine


def create_db_engine(db_path: str, *, embedding_dim: int = 1024) -> Engine:
    """SQLite の Engine を作り、通常テーブルと Embedding 用 vec0 テーブルを用意して返す.

    ADR-0011により Ingest 時の Embedding 生成は一時停止しているが、既存の
    保存済みベクトルを読める状態に保つため vec0 テーブル自体は作り続ける。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    register_vec_extension(engine)
    SQLModel.metadata.create_all(engine)
    create_vector_table(engine, dim=embedding_dim)
    return engine
