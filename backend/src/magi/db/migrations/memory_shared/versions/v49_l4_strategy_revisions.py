"""Track procedural strategy revisions and consumed execution traces."""

from alembic import op

revision = "v49_l4_strategy_revisions"
down_revision = "v48_history_import_l2_reimport"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE procedural_skills ADD COLUMN strategy_revision INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE l4_execution_traces ADD COLUMN strategy_processed_at REAL",
    "CREATE INDEX idx_l4_pending_traces ON l4_execution_traces(skill_id, strategy_processed_at, created_at)",
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX idx_l4_pending_traces")
    op.execute("ALTER TABLE l4_execution_traces DROP COLUMN strategy_processed_at")
    op.execute("ALTER TABLE procedural_skills DROP COLUMN strategy_revision")
