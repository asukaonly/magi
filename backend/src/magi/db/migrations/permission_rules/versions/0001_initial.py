"""permission_rules baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
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


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript("DROP TABLE IF EXISTS permission_rules;")
