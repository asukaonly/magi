"""persona_registry baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06

Materialises the canonical persona-registry schema (personas,
persona_active) on a fresh database. This revision is the snapshot
of the schema as it stood the day Alembic took ownership; any
further evolution is a new revision file.
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS personas (
    persona_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    locale        TEXT NOT NULL DEFAULT 'en',
    config_json   TEXT NOT NULL,
    avatar_path   TEXT,
    group_name    TEXT NOT NULL DEFAULT 'general',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_builtin    INTEGER NOT NULL DEFAULT 0,
    seed_slug     TEXT,
    description   TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    deleted_at    REAL
);

CREATE TABLE IF NOT EXISTS persona_active (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    persona_id    TEXT NOT NULL REFERENCES personas(persona_id)
);
"""

DROP_SQL = """
DROP TABLE IF EXISTS persona_active;
DROP TABLE IF EXISTS personas;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
