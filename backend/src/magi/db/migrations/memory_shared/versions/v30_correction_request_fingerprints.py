"""Persist immutable request identities for memory corrections.

Revision ID: v30_correction_request_fingerprints
Revises: v29_correction_revert_blocks
"""

from __future__ import annotations

from alembic import op

revision = "v30_correction_request_fingerprints"
down_revision = "v29_correction_revert_blocks"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE memory_correction_request_fingerprints (
    correction_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE
);
"""


DROP_SQL = """
DROP TABLE IF EXISTS memory_correction_request_fingerprints;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v30_correction_request_fingerprints")
    try:
        connection.execute(
            """
            CREATE TABLE memory_correction_request_fingerprints (
                correction_id TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
                    ON DELETE CASCADE
            )
            """
        )
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v30_correction_request_fingerprints")
        connection.execute("RELEASE SAVEPOINT v30_correction_request_fingerprints")
        raise
    connection.execute("RELEASE SAVEPOINT v30_correction_request_fingerprints")


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute(
        "SELECT COUNT(*) FROM memory_correction_request_fingerprints"
    ).fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade correction request fingerprints while history exists")
    connection.execute("DROP TABLE IF EXISTS memory_correction_request_fingerprints")


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
