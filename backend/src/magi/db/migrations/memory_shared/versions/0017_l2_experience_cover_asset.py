"""Add user-selected cover assets to L2 experiences.

Revision ID: 0017_l2_experience_cover_asset
Revises: 0016_l2_experience_seeds
Create Date: 2026-06-22
"""

from __future__ import annotations

from alembic import op

revision = "0017_l2_experience_cover_asset"
down_revision = "0016_l2_experience_seeds"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
ALTER TABLE experiences ADD COLUMN user_cover_asset_ref TEXT;
"""


def _experience_columns(conn) -> set[str]:
    cursor = conn.execute("PRAGMA table_info(experiences)")
    return {row[1] for row in cursor.fetchall()}


def upgrade() -> None:
    conn = op.get_bind().connection
    if "user_cover_asset_ref" not in _experience_columns(conn):
        conn.executescript(SCHEMA_SQL)


def downgrade() -> None:
    conn = op.get_bind().connection
    if "user_cover_asset_ref" in _experience_columns(conn):
        conn.execute("ALTER TABLE experiences DROP COLUMN user_cover_asset_ref")
