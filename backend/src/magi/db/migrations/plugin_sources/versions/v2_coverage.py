"""Persist accepted scope coverage atomically with source checkpoints."""
from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE source_coverage (
            connection_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            checkpoint_revision INTEGER NOT NULL,
            coverage_json TEXT NOT NULL,
            accepted_at REAL NOT NULL,
            PRIMARY KEY(connection_id, source_id),
            FOREIGN KEY(connection_id, source_id)
                REFERENCES source_checkpoints(connection_id, source_id)
        )
    """)


def downgrade() -> None:
    op.drop_table("source_coverage")
