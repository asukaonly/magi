from __future__ import annotations

import sqlite3

from magi.db.migrations.memory_shared.versions.v36_history_imports import (
    CREATE_STATEMENTS,
    schema_sql_for_fresh_database,
)
from magi.db.migrations.memory_shared.versions.v37_history_import_selection import (
    SCHEMA_SQL as SELECTION_SCHEMA_SQL,
    revision,
)
from _shared.memory_schema import MEMORY_SHARED_MIGRATIONS


def test_history_import_migration_creates_job_and_record_tables() -> None:
    db = sqlite3.connect(":memory:")
    try:
        for statement in CREATE_STATEMENTS:
            db.execute(statement)
        db.executescript(SELECTION_SCHEMA_SQL)
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert "history_import_jobs" in tables
        assert "history_import_records" in tables
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(history_import_jobs)").fetchall()
        }
        assert "included_files_json" in columns
    finally:
        db.close()


def test_history_import_selection_precedes_the_release_head() -> None:
    assert MEMORY_SHARED_MIGRATIONS[-1] == "v42_l2_projection_batch_descriptors.py"
    assert MEMORY_SHARED_MIGRATIONS[-6] == "v37_history_import_selection.py"
    assert revision == "v37_history_import_selection"
    assert "CREATE TABLE IF NOT EXISTS history_import_jobs" in (schema_sql_for_fresh_database())
