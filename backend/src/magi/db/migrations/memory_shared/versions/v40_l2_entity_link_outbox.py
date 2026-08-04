"""Add the durable cross-database L2 entity-link projection outbox."""

from __future__ import annotations

from alembic import op

revision = "v40_l2_entity_link_outbox"
down_revision = "v39_l2_projection_leases"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l2_event_entity_link_outbox (
    event_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    batch_key TEXT NOT NULL CHECK (TRIM(batch_key) != ''),
    lease_token TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
    clear_generation INTEGER NOT NULL CHECK (clear_generation >= 0),
    desired_links_json TEXT NOT NULL CHECK (json_valid(desired_links_json)),
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'ready', 'applied', 'discarded')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    applied_at REAL,
    PRIMARY KEY(event_id, revision),
    UNIQUE(event_id, batch_key)
);

CREATE INDEX IF NOT EXISTS idx_l2_event_entity_link_outbox_pending
    ON l2_event_entity_link_outbox(state, updated_at, event_id, revision);

CREATE INDEX IF NOT EXISTS idx_l2_event_entity_link_outbox_attempt
    ON l2_event_entity_link_outbox(batch_key, state, event_id, revision);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def schema_sql_for_fresh_database() -> str:
    """Return the release schema addition for a fresh shared-memory database."""

    return SCHEMA_SQL


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_l2_event_entity_link_outbox_attempt")
    op.execute("DROP INDEX IF EXISTS idx_l2_event_entity_link_outbox_pending")
    op.execute("DROP TABLE IF EXISTS l2_event_entity_link_outbox")


__all__ = ["SCHEMA_SQL", "downgrade", "schema_sql_for_fresh_database", "upgrade"]
