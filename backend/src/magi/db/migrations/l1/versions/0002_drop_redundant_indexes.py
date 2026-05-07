"""Drop redundant l1_event_entities event-only index

Revision ID: 0002_drop_redundant_indexes
Revises: 0001_initial
Create Date: 2026-05-07

idx_l1_event_entities_event(event_id) is fully covered by
UNIQUE(event_id, entity_id), which already serves all
``WHERE event_id = ?`` lookups against the table.
"""
from __future__ import annotations

from alembic import op


revision = "0002_drop_redundant_indexes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_l1_event_entities_event")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_l1_event_entities_event "
        "ON l1_event_entities(event_id)"
    )
