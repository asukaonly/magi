"""Index replacement slots used by identity-merge correction safety.

Revision ID: v31_correction_replacement_slot_index
Revises: v30_correction_request_fingerprints
"""

from __future__ import annotations

from alembic import op

revision = "v31_correction_replacement_slot_index"
down_revision = "v30_correction_request_fingerprints"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE INDEX idx_memory_corrections_active_replacement_slot
    ON memory_corrections(
        target_kind,
        (
            CASE WHEN json_valid(replacement_json)
            THEN json_extract(replacement_json, '$.slot_key') END
        ),
        created_at
    )
    WHERE state = 'active' AND transition_cancelled_at IS NULL;
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_corrections_active_replacement_slot;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute(DROP_SQL)


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
