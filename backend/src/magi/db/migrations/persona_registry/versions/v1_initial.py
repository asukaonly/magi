"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
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
