"""sqlite-vec を使った Embedding の永続化.

Embedding は SQLModel の table クラスでは表現できない sqlite-vec の vec0 仮想
テーブルに格納するため、この層だけ生 SQL(`exec_driver_sql`)で扱う。

ADR-0011により Ingest 時の Embedding 生成は一時停止しており、`save_embeddings`
は現在どこからも呼ばれていない(意図的な一時停止であり削除ではないため、
再開時の手戻りを減らすためコードは残す)。`register_vec_extension`/
`create_vector_table` は既存の保存済みベクトルを読める状態に保つため
`db/session.py` から引き続き呼ばれる。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlite_vec
from sqlalchemy import event

if TYPE_CHECKING:
    import sqlite3

    from sqlalchemy import Engine
    from sqlalchemy.pool import ConnectionPoolEntry

    from polaris.domain.entities import EmbeddingRecord

_TABLE_NAME = "embeddings"


def register_vec_extension(engine: Engine) -> None:
    """Engine が新しい DBAPI コネクションを作るたびに sqlite-vec 拡張をロードする."""

    @event.listens_for(engine, "connect")
    def _load_vec_extension(dbapi_connection: sqlite3.Connection, _connection_record: ConnectionPoolEntry) -> None:
        dbapi_connection.enable_load_extension(True)
        sqlite_vec.load(dbapi_connection)
        dbapi_connection.enable_load_extension(False)


def create_vector_table(engine: Engine, *, dim: int) -> None:
    """chunk_id をキーに固定次元の vector を保持する vec0 仮想テーブルを作る."""
    with engine.connect() as conn:
        conn.exec_driver_sql(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE_NAME} USING "
            f"vec0(chunk_id TEXT PRIMARY KEY, vector float[{dim}], +model TEXT)"
        )
        conn.commit()


def save_embeddings(engine: Engine, records: list[EmbeddingRecord]) -> None:
    """Chunk の Embedding をまとめて vec0 テーブルへ保存する."""
    with engine.connect() as conn:
        for record in records:
            conn.exec_driver_sql(
                f"INSERT INTO {_TABLE_NAME}(chunk_id, vector, model) VALUES (?, ?, ?)",  # noqa: S608
                (record.chunk_id, sqlite_vec.serialize_float32(record.vector), record.model),
            )
        conn.commit()
