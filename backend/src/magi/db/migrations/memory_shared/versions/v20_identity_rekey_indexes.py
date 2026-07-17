"""Add bounded lookup indexes for memory identity rekeys.

Revision ID: v20_identity_rekey_indexes
Revises: v19_claim_evidence_ledger
"""

from __future__ import annotations

from alembic import op

revision = "v20_identity_rekey_indexes"
down_revision = "v19_claim_evidence_ledger"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE INDEX IF NOT EXISTS idx_tom_assertions_target_entity_updated
    ON tom_trait_assertions(target_entity_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_corrections_replacement_created
    ON memory_corrections(target_kind, replacement_target_id, created_at DESC);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_corrections_replacement_created;
DROP INDEX IF EXISTS idx_tom_assertions_target_entity_updated;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v20_identity_rekey_indexes")
    try:
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_tom_assertions_target_entity_updated
            ON tom_trait_assertions(target_entity_id, updated_at DESC)
            """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_corrections_replacement_created
            ON memory_corrections(target_kind, replacement_target_id, created_at DESC)
            """)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v20_identity_rekey_indexes")
        connection.execute("RELEASE SAVEPOINT v20_identity_rekey_indexes")
        raise
    connection.execute("RELEASE SAVEPOINT v20_identity_rekey_indexes")


def downgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v20_identity_rekey_indexes_down")
    try:
        connection.execute("DROP INDEX IF EXISTS idx_memory_corrections_replacement_created")
        connection.execute("DROP INDEX IF EXISTS idx_tom_assertions_target_entity_updated")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v20_identity_rekey_indexes_down")
        connection.execute("RELEASE SAVEPOINT v20_identity_rekey_indexes_down")
        raise
    connection.execute("RELEASE SAVEPOINT v20_identity_rekey_indexes_down")


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
