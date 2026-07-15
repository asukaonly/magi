"""Key current assertions by governed slot and scope.

Revision ID: v5_assertion_scope_uniqueness
Revises: v4_memory_corrections
"""

from alembic import op

revision = "v5_assertion_scope_uniqueness"
down_revision = "v4_memory_corrections"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
DROP INDEX IF EXISTS idx_tom_assertions_active_unique;
CREATE UNIQUE INDEX idx_tom_assertions_active_unique
    ON tom_trait_assertions(slot_key, scope_key)
    WHERE status NOT IN ('superseded', 'archived', 'expired', 'user_rejected', 'shadow');
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_tom_assertions_active_unique;
CREATE UNIQUE INDEX idx_tom_assertions_active_unique
    ON tom_trait_assertions(entity_id, entity_type, trait_name, target_entity_id)
    WHERE status NOT IN ('superseded', 'archived', 'expired', 'user_rejected', 'shadow');
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
