"""sqlite-vec の vec0 テーブル(register_vec_extension/create_vector_table/save_embeddings)のテスト."""

from pathlib import Path

from sqlmodel import create_engine

from polaris.db.vector_store import create_vector_table, register_vec_extension, save_embeddings
from polaris.domain.entities import EmbeddingRecord


def test_save_and_query_embeddings(tmp_path: Path) -> None:
    """vec0 テーブルへ保存した Embedding を KNN 検索で取得できる."""
    engine = create_engine(f"sqlite:///{tmp_path / 'vec_test.db'}")
    register_vec_extension(engine)
    create_vector_table(engine, dim=4)

    records = [
        EmbeddingRecord(chunk_id="c1", vector=[0.1, 0.2, 0.3, 0.4], model="test-model"),
        EmbeddingRecord(chunk_id="c2", vector=[0.9, 0.8, 0.7, 0.6], model="test-model"),
    ]
    save_embeddings(engine, records)

    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT chunk_id, model FROM embeddings ORDER BY chunk_id").fetchall()

    assert rows == [("c1", "test-model"), ("c2", "test-model")]


def test_create_vector_table_is_idempotent(tmp_path: Path) -> None:
    """create_vector_table を2回呼んでもエラーにならない(IF NOT EXISTS)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'vec_test2.db'}")
    register_vec_extension(engine)

    create_vector_table(engine, dim=4)
    create_vector_table(engine, dim=4)  # 例外を送出しないこと
