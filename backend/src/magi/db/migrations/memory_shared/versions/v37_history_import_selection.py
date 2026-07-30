"""Persist the selected file scope for one-shot history imports."""

from __future__ import annotations

from alembic import op

revision = "v37_history_import_selection"
down_revision = "v36_history_imports"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
ALTER TABLE history_import_jobs
    ADD COLUMN included_files_json TEXT NOT NULL DEFAULT '[]';
UPDATE history_import_jobs
SET included_files_json = source_files_json
WHERE included_files_json = '[]';
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE history_import_jobs "
        "ADD COLUMN included_files_json TEXT NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "UPDATE history_import_jobs "
        "SET included_files_json = source_files_json "
        "WHERE included_files_json = '[]'"
    )


def schema_sql_for_fresh_database() -> str:
    """Return the release schema addition for a fresh shared-memory database."""

    return SCHEMA_SQL


def downgrade() -> None:
    op.execute("ALTER TABLE history_import_jobs DROP COLUMN included_files_json")


__all__ = [
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
