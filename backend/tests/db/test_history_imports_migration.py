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
from magi.db.migrations.memory_shared.versions.v47_history_import_deletion_privacy import (
    SCHEMA_SQL as DELETION_PRIVACY_SQL,
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
    assert MEMORY_SHARED_MIGRATIONS[-1] == "v48_history_import_l2_reimport.py"
    assert "v37_history_import_selection.py" in MEMORY_SHARED_MIGRATIONS
    assert revision == "v37_history_import_selection"
    assert "CREATE TABLE IF NOT EXISTS history_import_jobs" in (schema_sql_for_fresh_database())


def test_deleted_history_import_migration_redacts_payload_and_releases_barriers() -> None:
    db = sqlite3.connect(":memory:")
    try:
        db.execute(
            "CREATE TABLE l2_projection_jobs(" "event_id TEXT PRIMARY KEY, source TEXT NOT NULL)"
        )
        db.execute(
            """
            CREATE TABLE memory_source_event_tombstones(
                event_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        for statement in CREATE_STATEMENTS:
            db.execute(statement)
        db.executescript(SELECTION_SCHEMA_SQL)
        db.executescript(IMPORTER_SCHEMA_SQL)
        db.executemany(
            """
            INSERT INTO history_import_jobs(
                job_id, source_type, source_fingerprint, source_ids_json,
                included_source_ids_json, detected_kind, status,
                self_participant_ids_json, warnings_json,
                created_at, updated_at, deleted_at
            ) VALUES (?, 'markdown', ?, ?, ?, 'document', ?, ?, ?, 1, 2, ?)
            """,
            (
                (
                    "deleted-job",
                    "private-fingerprint",
                    '["private.md"]',
                    '["private.md"]',
                    "deleted",
                    '["__document_author__"]',
                    '["private-warning"]',
                    2,
                ),
                (
                    "preview-job",
                    "preview-fingerprint",
                    '["private.md"]',
                    '["private.md"]',
                    "preview_ready",
                    "[]",
                    "[]",
                    None,
                ),
            ),
        )
        db.executemany(
            """
            INSERT INTO history_import_source_records(
                source_record_key, file_fingerprint, source_id, source_name,
                parsed_session_key, session_id, session_seq,
                speaker_id, speaker_name, message_key, speaker_role, content,
                event_at, timestamp_confidence, timestamp_anchor_source,
                calendar_timezone_id, event_id, created_at
            ) VALUES (?, ?, 'private.md', 'private.md', 'session', 'session', 0,
                      '__document_author__', '__document_author__', 'document',
                      'user', ?, 1, 'exact', 'source_timestamp', 'UTC', ?, 1)
            """,
            (
                ("shared-record", "shared-file", "shared private text", "event-shared"),
                ("orphan-record", "orphan-file", "orphan private text", "event-orphan"),
            ),
        )
        db.executemany(
            """
            INSERT INTO history_import_job_records(
                job_record_id, job_id, source_record_key,
                source_order, created_at, updated_at
            ) VALUES (?, ?, ?, 0, 1, 1)
            """,
            (
                ("deleted-shared", "deleted-job", "shared-record"),
                ("deleted-orphan", "deleted-job", "orphan-record"),
                ("preview-shared", "preview-job", "shared-record"),
            ),
        )
        db.executemany(
            "INSERT INTO memory_source_event_tombstones(event_id, reason, created_at) "
            "VALUES (?, ?, 1)",
            (
                ("event-orphan", "history_import_deleted"),
                ("ordinary-event", "user_delete_event"),
            ),
        )

        db.executescript(DELETION_PRIVACY_SQL)

        deleted_job = db.execute(
            """
            SELECT source_type, source_fingerprint, source_ids_json,
                   included_source_ids_json, detected_kind,
                   self_participant_ids_json, warnings_json,
                   total_records, imported_count
            FROM history_import_jobs
            WHERE job_id = 'deleted-job'
            """
        ).fetchone()
        assert deleted_job == (
            "deleted",
            "deleted:deleted-job",
            "[]",
            "[]",
            "deleted",
            "[]",
            "[]",
            0,
            0,
        )
        assert db.execute(
            "SELECT job_id, source_record_key FROM history_import_job_records"
        ).fetchall() == [("preview-job", "shared-record")]
        assert db.execute(
            "SELECT source_record_key, content FROM history_import_source_records"
        ).fetchall() == [("shared-record", "shared private text")]
        assert db.execute(
            "SELECT event_id, reason FROM memory_source_event_tombstones"
        ).fetchall() == [("ordinary-event", "user_delete_event")]
    finally:
        db.close()
