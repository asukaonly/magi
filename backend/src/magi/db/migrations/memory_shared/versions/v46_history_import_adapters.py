"""Persist platform importer identity and stable source/message identifiers."""

from __future__ import annotations

from alembic import op

revision = "v46_history_import_adapters"
down_revision = "v45_profile_projection_highwaters"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE history_import_jobs RENAME COLUMN source_files_json TO source_ids_json",
    "ALTER TABLE history_import_jobs RENAME COLUMN included_files_json TO included_source_ids_json",
    "ALTER TABLE history_import_jobs RENAME COLUMN self_participants_json TO self_participant_ids_json",
    "ALTER TABLE history_import_jobs ADD COLUMN importer_plugin_id TEXT",
    "ALTER TABLE history_import_jobs ADD COLUMN importer_id TEXT",
    "ALTER TABLE history_import_jobs ADD COLUMN importer_format_version TEXT",
    "ALTER TABLE history_import_source_records ADD COLUMN source_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE history_import_source_records ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'document'",
    "ALTER TABLE history_import_source_records ADD COLUMN speaker_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE history_import_source_records ADD COLUMN message_key TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE history_import_source_records ADD COLUMN parent_message_key TEXT",
    "ALTER TABLE history_import_job_records ADD COLUMN source_order INTEGER NOT NULL DEFAULT 0",
    "UPDATE history_import_source_records SET source_id = source_name WHERE source_id = ''",
    "UPDATE history_import_source_records SET speaker_id = speaker_name WHERE speaker_id = ''",
    "UPDATE history_import_source_records SET message_key = 'document' WHERE message_key = ''",
    "UPDATE l2_projection_jobs SET source = 'history_import' "
    "WHERE source = 'history_import_markdown'",
    """
UPDATE history_import_job_records
SET source_order = (
    SELECT source.session_seq
    FROM history_import_source_records AS source
    WHERE source.source_record_key = history_import_job_records.source_record_key
)
""".strip(),
    """
CREATE INDEX IF NOT EXISTS idx_history_import_jobs_importer_state
ON history_import_jobs(
    importer_plugin_id, importer_id, importer_format_version,
    status, deleted_at, job_id
)
""".strip(),
    """
CREATE INDEX IF NOT EXISTS idx_history_import_source_session
ON history_import_source_records(
    source_id, parsed_session_key, source_record_key, message_key
)
""".strip(),
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def schema_sql_for_fresh_database() -> str:
    return SCHEMA_SQL


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_history_import_source_session")
    op.execute("DROP INDEX IF EXISTS idx_history_import_jobs_importer_state")
    op.execute(
        "UPDATE l2_projection_jobs SET source = 'history_import_markdown' "
        "WHERE source = 'history_import' AND event_type = 'history_import.document'"
    )
    op.execute("ALTER TABLE history_import_job_records DROP COLUMN source_order")
    op.execute("ALTER TABLE history_import_source_records DROP COLUMN parent_message_key")
    op.execute("ALTER TABLE history_import_source_records DROP COLUMN message_key")
    op.execute("ALTER TABLE history_import_source_records DROP COLUMN speaker_id")
    op.execute("ALTER TABLE history_import_source_records DROP COLUMN source_kind")
    op.execute("ALTER TABLE history_import_source_records DROP COLUMN source_id")
    op.execute("ALTER TABLE history_import_jobs DROP COLUMN importer_format_version")
    op.execute("ALTER TABLE history_import_jobs DROP COLUMN importer_id")
    op.execute("ALTER TABLE history_import_jobs DROP COLUMN importer_plugin_id")
    op.execute(
        "ALTER TABLE history_import_jobs "
        "RENAME COLUMN self_participant_ids_json TO self_participants_json"
    )
    op.execute(
        "ALTER TABLE history_import_jobs "
        "RENAME COLUMN included_source_ids_json TO included_files_json"
    )
    op.execute("ALTER TABLE history_import_jobs RENAME COLUMN source_ids_json TO source_files_json")


__all__ = ["SCHEMA_SQL", "STATEMENTS", "downgrade", "schema_sql_for_fresh_database", "upgrade"]
