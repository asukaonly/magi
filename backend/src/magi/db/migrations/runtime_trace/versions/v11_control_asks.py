"""Persist question state independently of permission prompts."""
from alembic import op

revision = "v11"
down_revision = "v10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().connection.executescript("""
CREATE TABLE control_asks (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    asked_at REAL NOT NULL,
    resolution TEXT CHECK (resolution IN ('user','timeout','cancelled')),
    state_json TEXT NOT NULL
);
CREATE INDEX idx_control_asks_session ON control_asks(session_id,asked_at);
CREATE UNIQUE INDEX idx_control_asks_pending ON control_asks(session_id) WHERE resolution IS NULL;
""")


def downgrade() -> None:
    op.execute("DROP TABLE control_asks")
