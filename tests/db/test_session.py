"""create_db_engineの列パッチ(_apply_column_patches)のテスト.

マイグレーション機構が無いプロジェクトで、既存の稼働中DBに`PaperRecord.text_path`
列を後から追加する仕組み(015-paper-qa-chat改訂、2026-09-13)。
"""

from pathlib import Path

import sqlalchemy
from sqlalchemy import text

from polaris.db.session import create_db_engine


def test_create_db_engine_adds_missing_column_to_existing_table_without_data_loss(tmp_path: Path) -> None:
    """`text_path`列が無い旧スキーマのDBに対し、既存データを保ったまま列を追加する."""
    db_path = tmp_path / "legacy.db"

    # text_path列が存在しない「旧スキーマ」を素のSQLiteで再現する。
    legacy_engine = sqlalchemy.create_engine(f"sqlite:///{db_path}")
    with legacy_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE paper_records ("
                "id VARCHAR PRIMARY KEY, item_id VARCHAR, authors JSON, year INTEGER, "
                "venue VARCHAR, doi VARCHAR, arxiv_id VARCHAR, abstract VARCHAR, "
                "source_url VARCHAR, pdf_path VARCHAR, ingested_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO paper_records (id, item_id, abstract, ingested_at) "
                "VALUES ('rec-1', 'item-1', 'existing abstract', '2026-09-13 00:00:00')"
            )
        )
    legacy_engine.dispose()

    engine = create_db_engine(str(db_path))

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(paper_records)"))}
        assert "text_path" in columns

        row = conn.execute(text("SELECT id, abstract, text_path FROM paper_records WHERE id = 'rec-1'")).one()
        assert row.abstract == "existing abstract"
        assert row.text_path is None


def test_create_db_engine_is_idempotent_when_column_already_exists(tmp_path: Path) -> None:
    """既に列がある状態(create_all直後、または2回目の起動)で呼んでもエラーにならない."""
    db_path = tmp_path / "fresh.db"

    create_db_engine(str(db_path))
    engine = create_db_engine(str(db_path))  # 2回目の呼び出し(ALTER TABLEを再度試みても壊れないこと)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(paper_records)"))}
        assert "text_path" in columns
