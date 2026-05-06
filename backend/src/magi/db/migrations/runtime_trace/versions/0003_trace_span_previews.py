"""add trace span preview columns

Revision ID: 0003_trace_span_previews
Revises: 0002_trace_context_columns
Create Date: 2026-05-06
"""

from __future__ import annotations

from alembic import op

revision = "0003_trace_span_previews"
down_revision = "0002_trace_context_columns"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    rows = op.get_bind().exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row[1]) == column_name for row in rows)


def _add_column_if_missing(table_name: str, column_sql: str, column_name: str) -> None:
    if not _has_column(table_name, column_name):
        op.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def upgrade() -> None:
    _add_column_if_missing("trace_spans", "input_preview TEXT", "input_preview")
    _add_column_if_missing("trace_spans", "output_preview TEXT", "output_preview")


def downgrade() -> None:
    for column_name in ("output_preview", "input_preview"):
        if _has_column("trace_spans", column_name):
            with op.batch_alter_table("trace_spans") as batch_op:
                batch_op.drop_column(column_name)
