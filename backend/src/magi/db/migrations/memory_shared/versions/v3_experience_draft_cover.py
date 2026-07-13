"""Persist user-selected covers on experience drafts.

Revision ID: v3_experience_draft_cover
Revises: v2_experience_drafts
"""

from alembic import op


revision = "v3_experience_draft_cover"
down_revision = "v2_experience_drafts"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE experience_drafts ADD COLUMN user_cover_asset_ref TEXT;
"""


DROP_SQL = """
ALTER TABLE experience_drafts DROP COLUMN user_cover_asset_ref;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
