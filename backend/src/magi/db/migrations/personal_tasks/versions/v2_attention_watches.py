"""Bounded explicit watches share the personal-content deletion owner."""

from alembic import op

revision = "v2_attention_watches"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE attention_watches (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, fields_json TEXT NOT NULL,
        version INTEGER NOT NULL, status TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        cursor_time REAL NOT NULL, cursor_id TEXT NOT NULL DEFAULT '',
        last_checked_at REAL, check_status TEXT NOT NULL DEFAULT 'waiting',
        result_json TEXT, evidence_json TEXT NOT NULL DEFAULT '{}', governance_revision TEXT,
        CHECK(status IN ('active','paused','stopped','matched','expired'))
    )""")
    op.execute(
        "CREATE INDEX idx_watches_owner ON attention_watches(user_id, status, updated_at DESC)"
    )
    op.execute("""CREATE TABLE attention_watch_receipts (
        user_id TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
        watch_id TEXT NOT NULL, PRIMARY KEY(user_id, request_id)
    )""")
    op.execute("""CREATE TABLE attention_watch_attempts (
        id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, watch_id TEXT NOT NULL, created_at REAL NOT NULL
    )""")
    op.execute("CREATE INDEX idx_watch_attempts ON attention_watch_attempts(user_id,created_at)")


def downgrade() -> None:
    for table in ("attention_watch_attempts", "attention_watch_receipts", "attention_watches"):
        op.drop_table(table)
