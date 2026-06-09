"""l1 pinned-payload satellite table (RFC #56 P3)

Revision ID: 0002_l1_event_payload
Revises: 0001_initial
Create Date: 2026-06-08

Adds ``l1_event_payload``, a sparse auxiliary table of ``fact_events``: a row
exists only when a sensor pinned the capture-time full text for an event
(obsidian note body, git commit text). ``fact_events.content`` stays a lean
summary so the timeline / L1 reads stay cheap; L2 reads the frozen full body
from here at extraction time, falling back to ``content`` when absent.

Like the other event-satellite tables (l1_event_embedding_state,
l1_event_entities) this keys on ``event_id`` without a hard FK — sqlite FK
enforcement is off by default and the satellite tables follow that convention.
"""
from __future__ import annotations

from alembic import op


revision = "0002_l1_event_payload"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS l1_event_payload (
    event_id   TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l1_event_payload_created_at
    ON l1_event_payload(created_at);
"""

DROP_SQL = """
DROP TABLE IF EXISTS l1_event_payload;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
