"""Track reversible, Claim-owned preference exclusions without copying content."""

from alembic import op

revision = "v54_preference_exclusions"
down_revision = "v53_gateway_read_indexes"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE l2_preference_exclusion_effects (
    target_kind TEXT NOT NULL CHECK (target_kind IN ('assertion', 'relationship')),
    target_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    before_status TEXT NOT NULL,
    before_valid_to REAL,
    effective_at REAL NOT NULL,
    applied_at REAL NOT NULL,
    PRIMARY KEY (target_kind, target_id)
);
CREATE INDEX idx_preference_exclusion_subject ON l2_preference_exclusion_effects(subject_id);
"""


def upgrade() -> None:
    for statement in SCHEMA_SQL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE l2_preference_exclusion_effects")
