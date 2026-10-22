"""Commit frozen question notifications alongside the question."""
from alembic import op

revision = "v12"
down_revision = "v11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().connection.executescript("""
CREATE TABLE control_ask_deliveries (
    delivery_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES control_asks(request_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    endpoint_json TEXT NOT NULL,
    content_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','leased','sending','succeeded','uncertain','failed','expired','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retry_safe INTEGER NOT NULL DEFAULT 0,
    next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    expires_at_ms INTEGER NOT NULL,
    receipt_json TEXT,
    last_error TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(request_id,endpoint_json)
);
CREATE INDEX idx_control_ask_delivery_ready ON control_ask_deliveries(state,next_attempt_at_ms,created_at_ms);
""")


def downgrade() -> None:
    op.execute("DROP TABLE control_ask_deliveries")
