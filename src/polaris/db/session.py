"""DB エンジンの生成."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlmodel import SQLModel, create_engine

from polaris.db.vector_store import create_vector_table, register_vec_extension

if TYPE_CHECKING:
    from sqlalchemy import Engine

# マイグレーション機構が無いプロジェクトで、既存の稼働中DBに後から列を追加する
# ための最小限の仕組み(015-paper-qa-chat改訂、2026-09-13が最初の適用例)。
# `SQLModel.metadata.create_all()`は新規テーブルの作成のみを行い、既存テーブルへの
# 列追加は行わないため、起動時にここで冪等にパッチする。
_COLUMN_PATCHES: tuple[tuple[str, str, str], ...] = (
    ("paper_records", "text_path", "VARCHAR"),
)


def _apply_column_patches(engine: Engine) -> None:
    """`_COLUMN_PATCHES`に列挙した列が無ければ`ALTER TABLE ... ADD COLUMN`で追加する."""
    with engine.begin() as conn:
        for table_name, column_name, column_type in _COLUMN_PATCHES:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})"))}
            if column_name not in existing:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


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
    _apply_column_patches(engine)
    create_vector_table(engine, dim=embedding_dim)
    return engine
