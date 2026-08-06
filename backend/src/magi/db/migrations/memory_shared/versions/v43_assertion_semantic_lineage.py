"""Persist assertion semantic lineage and target-window envelopes."""

from __future__ import annotations

from alembic import op

revision = "v43_assertion_semantic_lineage"
down_revision = "v42_l2_projection_batch_descriptors"
branch_labels = None
depends_on = None


ALTER_STATEMENTS = (
    "ALTER TABLE tom_trait_assertions ADD COLUMN semantic_lineage_key TEXT NOT NULL DEFAULT ''",
    """
ALTER TABLE tom_trait_assertions
    ADD COLUMN target_window_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(target_window_json))
""",
    """
CREATE INDEX IF NOT EXISTS idx_tom_assertions_semantic_lineage
    ON tom_trait_assertions(
        entity_id, trait_family, semantic_lineage_key, status, updated_at DESC
    )
""",
)
SCHEMA_SQL = ";\n".join(statement.strip() for statement in ALTER_STATEMENTS) + ";"


def upgrade() -> None:
    for statement in ALTER_STATEMENTS:
        op.execute(statement.strip())


def schema_sql_for_fresh_database() -> str:
    """Return the release schema addition for a fresh shared-memory database."""

    return SCHEMA_SQL


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tom_assertions_semantic_lineage")
    op.execute("ALTER TABLE tom_trait_assertions DROP COLUMN target_window_json")
    op.execute("ALTER TABLE tom_trait_assertions DROP COLUMN semantic_lineage_key")


__all__ = [
    "ALTER_STATEMENTS",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
