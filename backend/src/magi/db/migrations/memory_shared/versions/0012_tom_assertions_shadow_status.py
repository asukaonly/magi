"""Add 'shadow' to the active-unique index exclusion set for tom_trait_assertions.

Lets an inferred assertion that contradicts an authoritative one persist as a
'shadow' sibling on the same (entity, trait_name, target) key without tripping
idx_tom_assertions_active_unique. SQLite cannot ALTER a partial index's WHERE,
so we DROP + CREATE. Idempotent.

Revision ID: 0012_tom_assertions_shadow_status
Revises: 0011_l0_execution_run_trigger
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op

revision = "0012_tom_assertions_shadow_status"
down_revision = "0011_l0_execution_run_trigger"
branch_labels = None
depends_on = None

_DROP = "DROP INDEX IF EXISTS idx_tom_assertions_active_unique;"
_CREATE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tom_assertions_active_unique "
    "ON tom_trait_assertions(entity_id, entity_type, trait_name, target_entity_id) "
    "WHERE status NOT IN "
    "('superseded', 'archived', 'expired', 'user_rejected', 'shadow');"
)
_CREATE_OLD = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tom_assertions_active_unique "
    "ON tom_trait_assertions(entity_id, entity_type, trait_name, target_entity_id) "
    "WHERE status NOT IN ('superseded', 'archived', 'expired', 'user_rejected');"
)


def apply(conn) -> None:
    """Raw-connection helper (used by tests and by upgrade()).

    Accepts any object with an ``executescript`` method — works with both a
    plain ``sqlite3.Connection`` (tests) and the SQLAlchemy connection
    returned by ``op.get_bind().connection`` (Alembic runtime).
    """
    conn.executescript(_DROP + _CREATE)


def upgrade() -> None:
    conn = op.get_bind().connection
    apply(conn)


def downgrade() -> None:
    conn = op.get_bind().connection
    conn.executescript(_DROP + _CREATE_OLD)
