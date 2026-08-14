"""Physically remove legacy soft-deleted history-import L1 rows."""

from __future__ import annotations

from alembic import op

revision = "v4_history_import_deletion_privacy"
down_revision = "v3_unify_history_import_source"
branch_labels = None
depends_on = None


_DELETED_HISTORY_EVENT_IDS = """
SELECT event_id
FROM fact_events
WHERE source = 'history_import' AND deleted_at IS NOT NULL
""".strip()

STATEMENTS = (
    f"DELETE FROM l1_events_fts WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    f"DELETE FROM l1_projected_event_entities " f"WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    f"DELETE FROM l1_event_entity_projection_state "
    f"WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    f"DELETE FROM l1_event_entities WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    f"DELETE FROM l1_source_facets WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    f"DELETE FROM l1_event_chunks WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    f"DELETE FROM l1_event_embedding_state WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    f"DELETE FROM l1_event_payload WHERE event_id IN ({_DELETED_HISTORY_EVENT_IDS})",
    "DELETE FROM fact_events " "WHERE source = 'history_import' AND deleted_at IS NOT NULL",
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def schema_sql_for_fresh_database() -> str:
    """Return the release-time privacy cleanup for fresh L1 databases."""

    return SCHEMA_SQL


def downgrade() -> None:
    """Deleted user content cannot be reconstructed."""


__all__ = [
    "SCHEMA_SQL",
    "STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
