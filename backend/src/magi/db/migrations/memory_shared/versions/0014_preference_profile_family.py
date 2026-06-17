"""Rename removed taste_profile assertion family to preference_profile.

Revision ID: 0014_preference_profile_family
Revises: 0013_tom_assertions_shadow_status
Create Date: 2026-06-17

The L2 ontology now uses preference_profile for durable interests, affinities,
tastes, and preferences. This migration normalizes existing rows once so the
runtime does not need a compatibility branch for the removed taste_profile
family.
"""

from __future__ import annotations

from alembic import op

revision = "0014_preference_profile_family"
down_revision = "0013_tom_assertions_shadow_status"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
UPDATE tom_trait_assertions
SET trait_family = 'preference_profile'
WHERE trait_family = 'taste_profile';
"""

DOWN_SQL = """
UPDATE tom_trait_assertions
SET trait_family = 'taste_profile'
WHERE trait_family = 'preference_profile'
  AND (
    trait_name LIKE 'taste.%'
    OR trait_name = 'taste_preference'
  );
"""


def apply(conn) -> None:
    """Apply the data normalization using a raw sqlite connection."""

    conn.executescript(SCHEMA_SQL)


def upgrade() -> None:
    apply(op.get_bind().connection)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWN_SQL)
