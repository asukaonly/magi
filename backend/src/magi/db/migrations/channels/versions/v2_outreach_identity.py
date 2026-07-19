"""Give every external outreach intent one durable channel-scoped identity."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


FINAL_SCHEMA_SQL = """
CREATE TABLE outreach_outbox (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id     TEXT    NOT NULL,
    channel_scope      TEXT    NOT NULL,
    intent_fingerprint TEXT    NOT NULL,
    intent_json        TEXT    NOT NULL,
    release_at_ms      INTEGER NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending',
    created_at_ms      INTEGER NOT NULL
);

CREATE INDEX ix_outreach_outbox_due
    ON outreach_outbox (status, release_at_ms);

CREATE UNIQUE INDEX uq_outreach_outbox_identity
    ON outreach_outbox (correlation_id, channel_scope);
"""


def _outbox_columns() -> set[str]:
    connection = op.get_bind()
    rows = connection.exec_driver_sql(
        "PRAGMA table_info(outreach_outbox)"
    ).fetchall()
    return {str(row[1]) for row in rows}


def upgrade() -> None:
    connection = op.get_bind()
    required = {
        "correlation_id",
        "channel_scope",
        "intent_fingerprint",
    }
    if not required <= _outbox_columns():
        # This project is pre-release. Old pending rows have no reliable
        # logical identity, so guessing or merging them would risk duplicates.
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_outreach_outbox_due")
        connection.exec_driver_sql("DROP TABLE outreach_outbox")
        connection.connection.executescript(FINAL_SCHEMA_SQL)
        return
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_outreach_outbox_due "
        "ON outreach_outbox (status, release_at_ms)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_outbox_identity "
        "ON outreach_outbox (correlation_id, channel_scope)"
    )


def downgrade() -> None:
    # The current v1 release baseline already contains this final schema.
    connection = op.get_bind()
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_outreach_outbox_due "
        "ON outreach_outbox (status, release_at_ms)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_outbox_identity "
        "ON outreach_outbox (correlation_id, channel_scope)"
    )
