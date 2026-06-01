"""manual memory entries

Revision ID: 0007_manual_entries
Revises: 0006_location_samples
Create Date: 2026-05-20

Tables for user-authored memory entries (Phase A of P11):

  manual_entries     a single row per user note. Carries body + optional
                     mood / location / image attachments, and a back-pointer
                     to the L1 event the entry projects to so updates can
                     re-issue / soft-deletes can tombstone the L1 row.

Reserved-for-future columns (title, tags, related_episode_ids,
exclude_from_llm beyond the simple flag) are deliberately omitted —
adding nullable columns later is cheap; carrying unused ones now would
muddle the migration.
"""

from __future__ import annotations

from alembic import op

revision = "0007_manual_entries"
down_revision = "0006_location_samples"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS manual_entries (
    entry_id          TEXT PRIMARY KEY,
    created_at        REAL NOT NULL,
    event_at          REAL NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'quick',
    body              TEXT NOT NULL,
    mood              TEXT,
    location_label    TEXT,
    location_lat      REAL,
    location_lng      REAL,
    attachments_json  TEXT NOT NULL DEFAULT '[]',
    exclude_from_llm  INTEGER NOT NULL DEFAULT 0,
    user_pinned       INTEGER NOT NULL DEFAULT 0,
    deleted_at        REAL,
    l1_event_id       TEXT
);
CREATE INDEX IF NOT EXISTS idx_manual_entries_event_at
    ON manual_entries(event_at DESC);
CREATE INDEX IF NOT EXISTS idx_manual_entries_active
    ON manual_entries(deleted_at, event_at DESC)
    WHERE deleted_at IS NULL;
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_manual_entries_active;
DROP INDEX IF EXISTS idx_manual_entries_event_at;
DROP TABLE IF EXISTS manual_entries;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
