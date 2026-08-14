"""Redact deleted history-import payloads and release replacement barriers."""

from __future__ import annotations

from alembic import op

revision = "v47_history_import_deletion_privacy"
down_revision = "v46_history_import_adapters"
branch_labels = None
depends_on = None


STATEMENTS = (
    "DELETE FROM memory_source_event_tombstones " "WHERE reason = 'history_import_deleted'",
    "DELETE FROM history_import_job_records "
    "WHERE job_id IN ("
    "SELECT job_id FROM history_import_jobs WHERE deleted_at IS NOT NULL"
    ")",
    "DELETE FROM history_import_source_records "
    "WHERE NOT EXISTS ("
    "SELECT 1 FROM history_import_job_records AS membership "
    "WHERE membership.source_record_key = "
    "history_import_source_records.source_record_key"
    ")",
    """
UPDATE history_import_jobs
SET source_type = 'deleted',
    source_fingerprint = 'deleted:' || job_id,
    source_ids_json = '[]',
    included_source_ids_json = '[]',
    importer_plugin_id = NULL,
    importer_id = NULL,
    importer_format_version = NULL,
    detected_kind = 'deleted',
    status = 'deleted',
    total_records = 0,
    meaningful_records = 0,
    quick_target_records = 0,
    quick_max_records = 0,
    quick_imported_count = 0,
    imported_count = 0,
    projected_count = 0,
    self_participant_ids_json = '[]',
    warnings_json = '[]',
    quick_ready = 0,
    error_text = NULL,
    updated_at = deleted_at
WHERE deleted_at IS NOT NULL
""".strip(),
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def schema_sql_for_fresh_database() -> str:
    """Return the release-time privacy cleanup for fresh databases."""

    return SCHEMA_SQL


def downgrade() -> None:
    """Deleted user content and released replacement barriers are irreversible."""


__all__ = [
    "SCHEMA_SQL",
    "STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
