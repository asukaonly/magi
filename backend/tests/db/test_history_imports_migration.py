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
from magi.db.migrations.memory_shared.versions.v46_history_import_adapters import (
    SCHEMA_SQL as IMPORTER_SCHEMA_SQL,
)
from _shared.memory_schema import MEMORY_SHARED_MIGRATIONS


def test_history_import_migration_creates_job_and_record_tables() -> None:
    db = sqlite3.connect(":memory:")
    try:
        db.execute(
            "CREATE TABLE l2_projection_jobs(" "event_id TEXT PRIMARY KEY, source TEXT NOT NULL)"
        )
        db.executemany(
            "INSERT INTO l2_projection_jobs(event_id, source) VALUES (?, ?)",
            (
                ("legacy-history", "history_import_markdown"),
                ("unrelated", "conversation"),
            ),
        )
        for statement in CREATE_STATEMENTS:
            db.execute(statement)
        db.executescript(SELECTION_SCHEMA_SQL)
        db.execute(
            """
            INSERT INTO history_import_jobs(
                job_id, source_type, source_fingerprint, source_files_json,
                included_files_json, detected_kind, status,
                self_participants_json, created_at, updated_at
            ) VALUES ('job-1', 'markdown', 'fingerprint', '["note.md"]',
                      '["note.md"]', 'document', 'completed',
                      '["__document_author__"]', 1, 1)
            """
        )
        db.execute(
            """
            INSERT INTO history_import_source_records(
                source_record_key, file_fingerprint, source_name,
                parsed_session_key, session_id, session_seq, speaker_name,
                content, event_at, timestamp_confidence,
                timestamp_anchor_source, calendar_timezone_id, event_id,
                created_at
            ) VALUES ('record-1', 'file-1', 'note.md', 'note.md',
                      'session-1', 7, '__document_author__', 'Text', 1,
                      'file_mtime', 'file_mtime', 'UTC', 'event-1', 1)
            """
        )
        db.execute(
            """
            INSERT INTO history_import_job_records(
                job_record_id, job_id, source_record_key, created_at, updated_at
            ) VALUES ('membership-1', 'job-1', 'record-1', 1, 1)
            """
        )
        db.executescript(IMPORTER_SCHEMA_SQL)
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert "history_import_jobs" in tables
        assert "history_import_source_records" in tables
        assert "history_import_job_records" in tables
        indexes = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        }
        assert {
            "idx_history_import_jobs_importer_state",
            "idx_history_import_source_session",
        }.issubset(indexes)
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(history_import_jobs)").fetchall()
        }
        assert {
            "source_ids_json",
            "included_source_ids_json",
            "self_participant_ids_json",
            "importer_plugin_id",
            "importer_id",
            "importer_format_version",
        }.issubset(columns)
        assert "source_files_json" not in columns
        assert "included_files_json" not in columns
        assert "self_participants_json" not in columns
        source_columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(history_import_source_records)").fetchall()
        }
        membership_columns = {
            row[1] for row in db.execute("PRAGMA table_info(history_import_job_records)").fetchall()
        }
        assert {
            "source_record_key",
            "file_fingerprint",
            "source_id",
            "source_kind",
            "parsed_session_key",
            "speaker_id",
            "message_key",
            "parent_message_key",
            "event_id",
        }.issubset(source_columns)
        assert {
            "job_record_id",
            "job_id",
            "source_record_key",
            "source_order",
            "raw_state",
            "projection_state",
        }.issubset(membership_columns)
        assert "raw_state" not in source_columns
        assert "content" not in membership_columns
        migrated_record = db.execute(
            "SELECT message_key, source_kind FROM history_import_source_records "
            "WHERE source_record_key = 'record-1'"
        ).fetchone()
        migrated_membership = db.execute(
            "SELECT source_order FROM history_import_job_records "
            "WHERE job_record_id = 'membership-1'"
        ).fetchone()
        assert migrated_record == ("document", "document")
        assert migrated_membership == (7,)
        assert db.execute(
            "SELECT event_id, source FROM l2_projection_jobs ORDER BY event_id"
        ).fetchall() == [
            ("legacy-history", "history_import"),
            ("unrelated", "conversation"),
        ]
    finally:
        db.close()


def test_history_import_selection_precedes_the_release_head() -> None:
    assert MEMORY_SHARED_MIGRATIONS[-1] == "v46_history_import_adapters.py"
    assert "v37_history_import_selection.py" in MEMORY_SHARED_MIGRATIONS
    assert revision == "v37_history_import_selection"
    assert "CREATE TABLE IF NOT EXISTS history_import_jobs" in (schema_sql_for_fresh_database())
