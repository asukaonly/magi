"""Preserve source-declared roles separately from confirmed user identity."""

from alembic import op

revision = "v58_history_import_source_roles"
down_revision = "v57_entity_identity_tombstones"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
ALTER TABLE history_import_source_records
ADD COLUMN source_role TEXT NOT NULL DEFAULT 'unknown'
CHECK(source_role IN ('user', 'assistant', 'other', 'unknown'));
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("ALTER TABLE history_import_source_records DROP COLUMN source_role")
