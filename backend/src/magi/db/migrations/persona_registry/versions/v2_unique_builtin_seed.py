"""Require one active builtin persona per seed slug."""

from __future__ import annotations

from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_personas_active_builtin_seed"


def upgrade() -> None:
    op.execute(
        f"""CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
        ON personas(seed_slug)
        WHERE is_builtin = 1 AND seed_slug IS NOT NULL AND deleted_at IS NULL"""
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
