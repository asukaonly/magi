"""Personal items and atomic mutation history."""

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE personal_items (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('action', 'project')),
    parent_id TEXT, title TEXT NOT NULL, body_md TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('inbox','active','waiting','someday','completed','cancelled')),
    defer_until TEXT, defer_epoch REAL, due TEXT, remind_at TEXT, timezone TEXT NOT NULL,
    references_json TEXT NOT NULL DEFAULT '[]', origin TEXT NOT NULL,
    version INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
    closed_at REAL, reminder_revision INTEGER NOT NULL DEFAULT 0,
    reminder_synced_revision INTEGER NOT NULL DEFAULT 0,
    reminder_delivered_revision INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX personal_items_owner_status ON personal_items(user_id, status, updated_at DESC);
CREATE INDEX personal_items_parent ON personal_items(user_id, parent_id);
CREATE TABLE personal_item_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, item_id TEXT NOT NULL,
    request_id TEXT NOT NULL, request_hash TEXT NOT NULL, action TEXT NOT NULL,
    actor TEXT NOT NULL, version INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '',
    changes_json TEXT NOT NULL DEFAULT '{}', references_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL, UNIQUE(user_id, request_id)
);
CREATE INDEX personal_changes_item ON personal_item_changes(user_id, item_id, id DESC);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.drop_table("personal_item_changes")
    op.drop_table("personal_items")
