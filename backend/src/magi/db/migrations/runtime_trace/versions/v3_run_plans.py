"""Add durable, versioned run plans."""

from __future__ import annotations

from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE run_plans (
    plan_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    required INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE UNIQUE INDEX idx_run_plans_run
    ON run_plans(run_id);

CREATE INDEX idx_run_plans_session_updated
    ON run_plans(session_id, updated_at_ms DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_run_plans_session_updated;
DROP INDEX IF EXISTS idx_run_plans_run;
DROP TABLE IF EXISTS run_plans;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
