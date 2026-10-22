"""Keep event scan identities monotonic across logical transfers and clear."""

from alembic import op
from sqlalchemy import inspect

revision = "v2_event_sequence"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("magi_l1_state")}
    if "event_sequence" not in columns:
        op.execute("ALTER TABLE magi_l1_state ADD COLUMN event_sequence BIGINT NOT NULL DEFAULT 0")
    op.execute("""
        UPDATE magi_l1_state SET event_sequence = GREATEST(
            event_sequence,
            (SELECT COALESCE(MAX(id), 0) FROM magi_l1_events),
            (SELECT COALESCE(AUTO_INCREMENT, 1) - 1 FROM information_schema.TABLES
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'magi_l1_events')
        ) WHERE singleton_id = 1
    """)


def downgrade() -> None:
    raise RuntimeError("Export memory events before changing their storage schema")
