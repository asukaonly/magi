"""Remove profile-setting diagnostics from retained fact descriptions."""
from __future__ import annotations

from alembic import op


revision = "v50_profile_fact_descriptions"
down_revision = "v49_l4_strategy_revisions"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
UPDATE tom_trait_assertions
SET natural_summary = ''
WHERE source_domain = 'settings_profile'
  AND natural_summary = 'User profile field ' || trait_name || ' was set from personal profile settings.';
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    """Do not restore diagnostics into a field reserved for retained facts."""
