"""add trace context columns

Revision ID: 0002_trace_context_columns
Revises: 0001_initial
Create Date: 2026-05-06
"""

from __future__ import annotations

from alembic import op

revision = "0002_trace_context_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    rows = op.get_bind().exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row[1]) == column_name for row in rows)


def _add_column_if_missing(table_name: str, column_sql: str, column_name: str) -> None:
    if not _has_column(table_name, column_name):
        op.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def upgrade() -> None:
    _add_column_if_missing("trace_turns", "run_id TEXT", "run_id")
    _add_column_if_missing(
        "trace_turns",
        "run_revision INTEGER NOT NULL DEFAULT 0",
        "run_revision",
    )
    _add_column_if_missing("trace_spans", "run_id TEXT", "run_id")
    _add_column_if_missing(
        "trace_spans",
        "run_revision INTEGER NOT NULL DEFAULT 0",
        "run_revision",
    )
    _add_column_if_missing(
        "trace_llm_calls",
        "thinking_depth TEXT NOT NULL DEFAULT 'none'",
        "thinking_depth",
    )
    _add_column_if_missing("runtime_notifications", "run_id TEXT", "run_id")
    _add_column_if_missing(
        "runtime_notifications",
        "run_revision INTEGER NOT NULL DEFAULT 0",
        "run_revision",
    )


def downgrade() -> None:
    for table_name, column_name in (
        ("runtime_notifications", "run_revision"),
        ("runtime_notifications", "run_id"),
        ("trace_llm_calls", "thinking_depth"),
        ("trace_spans", "run_revision"),
        ("trace_spans", "run_id"),
        ("trace_turns", "run_revision"),
        ("trace_turns", "run_id"),
    ):
        if _has_column(table_name, column_name):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_column(column_name)
