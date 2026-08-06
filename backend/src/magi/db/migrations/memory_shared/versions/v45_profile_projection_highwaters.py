"""Persist exact input highwaters for profile projections."""

from __future__ import annotations

from alembic import op

revision = "v45_profile_projection_highwaters"
down_revision = "v44_l2_pending_reviews"
branch_labels = None
depends_on = None


STATEMENTS = (
    "ALTER TABLE user_profile_projection "
    "ADD COLUMN input_assertion_highwater REAL NOT NULL DEFAULT 0",
    "ALTER TABLE user_portrait_projection "
    "ADD COLUMN input_assertion_highwater REAL NOT NULL DEFAULT 0",
    "ALTER TABLE user_portrait_projection "
    "ADD COLUMN input_claim_highwater REAL NOT NULL DEFAULT 0",
    "ALTER TABLE user_portrait_projection "
    "ADD COLUMN input_review_highwater REAL NOT NULL DEFAULT 0",
    "ALTER TABLE user_portrait_projection "
    "ADD COLUMN input_profile_highwater REAL NOT NULL DEFAULT 0",
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def schema_sql_for_fresh_database() -> str:
    """Return the projection-highwater schema for fresh databases."""

    return SCHEMA_SQL


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_portrait_projection DROP COLUMN input_profile_highwater"
    )
    op.execute(
        "ALTER TABLE user_portrait_projection DROP COLUMN input_review_highwater"
    )
    op.execute(
        "ALTER TABLE user_portrait_projection DROP COLUMN input_claim_highwater"
    )
    op.execute(
        "ALTER TABLE user_portrait_projection DROP COLUMN input_assertion_highwater"
    )
    op.execute(
        "ALTER TABLE user_profile_projection DROP COLUMN input_assertion_highwater"
    )


__all__ = [
    "SCHEMA_SQL",
    "STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
