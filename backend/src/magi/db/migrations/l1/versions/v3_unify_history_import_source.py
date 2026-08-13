"""Use one source identity for document and platform history imports."""

from __future__ import annotations

from alembic import op

revision = "v3_unify_history_import_source"
down_revision = "v2_l2_entity_link_projections"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
UPDATE fact_events
SET source = 'history_import'
WHERE source = 'history_import_markdown';
"""


def upgrade() -> None:
    op.execute(
        "UPDATE fact_events SET source = 'history_import' "
        "WHERE source = 'history_import_markdown'"
    )


def schema_sql_for_fresh_database() -> str:
    return SCHEMA_SQL


def downgrade() -> None:
    op.execute(
        "UPDATE fact_events SET source = 'history_import_markdown' "
        "WHERE source = 'history_import' AND event_type = 'history_import.document'"
    )


__all__ = ["SCHEMA_SQL", "downgrade", "schema_sql_for_fresh_database", "upgrade"]
