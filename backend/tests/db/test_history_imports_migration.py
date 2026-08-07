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
        assert "history_import_source_records" in tables
        assert "history_import_job_records" in tables
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(history_import_jobs)").fetchall()
        }
        assert "included_files_json" in columns
        source_columns = {
            row[1]
            for row in db.execute(
                "PRAGMA table_info(history_import_source_records)"
            ).fetchall()
        }
        membership_columns = {
            row[1]
            for row in db.execute(
                "PRAGMA table_info(history_import_job_records)"
            ).fetchall()
        }
        assert {
            "source_record_key",
            "file_fingerprint",
            "parsed_session_key",
            "event_id",
        }.issubset(source_columns)
        assert {
            "job_record_id",
            "job_id",
            "source_record_key",
            "raw_state",
            "projection_state",
        }.issubset(membership_columns)
        assert "raw_state" not in source_columns
        assert "content" not in membership_columns
    finally:
        db.close()


def test_history_import_selection_precedes_the_release_head() -> None:
    assert MEMORY_SHARED_MIGRATIONS[-1] == "v45_profile_projection_highwaters.py"
    assert "v37_history_import_selection.py" in MEMORY_SHARED_MIGRATIONS
    assert revision == "v37_history_import_selection"
    assert "CREATE TABLE IF NOT EXISTS history_import_jobs" in (schema_sql_for_fresh_database())
