"""Drop redundant runtime_notifications PK-shadow index

Revision ID: 0004_drop_redundant_indexes
Revises: 0003_trace_span_previews
Create Date: 2026-05-07

``runtime_notifications.notification_id`` is declared
``INTEGER PRIMARY KEY AUTOINCREMENT`` — in SQLite this column is the
table's rowid, which already has an implicit ordered index. The
explicit ``idx_runtime_notifications_created(notification_id ASC)``
adds nothing; it just duplicates the rowid index.
"""
from __future__ import annotations

from alembic import op


revision = "0004_drop_redundant_indexes"
down_revision = "0003_trace_span_previews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_runtime_notifications_created")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_notifications_created "
        "ON runtime_notifications(notification_id ASC)"
    )
