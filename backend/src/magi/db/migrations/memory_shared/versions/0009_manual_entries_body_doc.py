"""manual_entries.body_doc — rich-text document JSON

Revision ID: 0009_manual_entries_body_doc
Revises: 0008_manual_entries_weather
Create Date: 2026-05-20

Phase B-2: rich text body. The plain ``body`` column stays — it's what
L1 / search / diary LLM read, and keeping it as the canonical
projection means none of the downstream consumers need to learn
ProseMirror. The new ``body_doc TEXT NULL`` column stores the
ProseMirror JSON document; the renderer prefers it when non-null and
falls back to wrapping ``body`` in a single paragraph node otherwise.

Why a separate column instead of replacing body:
  - Backward compat is free: existing entries (body_doc=NULL) render as
    plain paragraphs without touching their row.
  - Lossless rich edit + cheap text consumption from the same row, no
    runtime ProseMirror→text conversion needed on every read.

The JSON is opaque to SQL — we never query into it — so TEXT (vs JSON
the type, which sqlite emulates as TEXT anyway) keeps things simple.
"""

from __future__ import annotations

from alembic import op

revision = "0009_manual_entries_body_doc"
down_revision = "0008_manual_entries_weather"
branch_labels = None
depends_on = None


# Named SCHEMA_SQL so the test schema helper picks it up alongside the
# other migrations on a fresh DB.
SCHEMA_SQL = """
ALTER TABLE manual_entries ADD COLUMN body_doc TEXT;
"""

DROP_SQL = """
ALTER TABLE manual_entries DROP COLUMN body_doc;
"""


def upgrade() -> None:
    """Add body_doc column — defensively.

    Same dev-drift defense as 0008: if the column was already added
    out-of-band (manual ALTER while the feature was in flight) and
    alembic_version wasn't bumped, a plain ALTER fails with
    'duplicate column name'. Introspect PRAGMA table_info first and
    skip the ALTER when the column already exists. Alembic still
    records the migration as applied, so subsequent boots are clean.
    """
    conn = op.get_bind().connection
    cursor = conn.execute("PRAGMA table_info(manual_entries)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "body_doc" not in existing_columns:
        conn.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
