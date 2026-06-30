"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS permission_rules (
    rule_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    matcher_json TEXT NOT NULL,
    allow INTEGER NOT NULL,
    note TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_perm_rules_tool
    ON permission_rules(tool_name);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_perm_rules_tool;

DROP TABLE IF EXISTS permission_rules;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
