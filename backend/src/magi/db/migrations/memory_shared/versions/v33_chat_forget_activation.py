"""Gate chat forgetting on a durable runtime barrier.

Revision ID: v33_chat_forget_activation
Revises: v32_forget_source_owner_refs
"""

from __future__ import annotations

import re
import sqlite3

from alembic import op

revision = "v33_chat_forget_activation"
down_revision = "v32_forget_source_owner_refs"
branch_labels = None
depends_on = None


_ADD_COLUMN_SQL = """
ALTER TABLE memory_forget_operations
    ADD COLUMN execution_ready INTEGER NOT NULL DEFAULT 1
        CHECK(execution_ready IN (0, 1));
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_memory_forget_operations_activation
    ON memory_forget_operations(
        execution_ready, status, lease_expires_at, updated_at, operation_id
    )
    WHERE status != 'completed';
"""

SCHEMA_SQL = f"{_ADD_COLUMN_SQL}\n{_CREATE_INDEX_SQL}"


def _table_sql(connection, table: str) -> str:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()
    return str(row[0] or "") if row is not None else ""


def _column_rows(connection, table: str) -> dict[str, tuple[object, ...]]:
    return {
        str(row[1]): tuple(row)
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _validate_execution_ready_column(connection) -> None:
    columns = _column_rows(connection, "memory_forget_operations")
    row = columns.get("execution_ready")
    if row is None:
        raise RuntimeError("Memory forget-operation activation column is missing")
    column_type = str(row[2] or "").strip().upper()
    not_null = int(row[3] or 0)
    default_value = str(row[4] or "").strip("() '\"")
    table_sql = _table_sql(connection, "memory_forget_operations")
    has_check = re.search(
        r"check\s*\(\s*execution_ready\s+in\s*"
        r"\(\s*0\s*,\s*1\s*\)\s*\)",
        table_sql,
        flags=re.IGNORECASE,
    )
    if (
        column_type != "INTEGER"
        or not_null != 1
        or default_value != "1"
        or has_check is None
    ):
        raise RuntimeError(
            "Memory forget-operation activation column has an unsupported schema"
        )


def _validate_activation_index(connection) -> None:
    index_name = "idx_memory_forget_operations_activation"
    index_rows = {
        str(row[1]): tuple(row)
        for row in connection.execute(
            "PRAGMA index_list(memory_forget_operations)"
        ).fetchall()
    }
    index_row = index_rows.get(index_name)
    if index_row is None or int(index_row[2] or 0) != 0:
        raise RuntimeError(
            "Memory forget-operation activation index has an unsupported schema"
        )
    columns = tuple(
        str(row[2])
        for row in connection.execute(
            f"PRAGMA index_info({index_name})"
        ).fetchall()
    )
    index_sql_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'index' AND name = ?
        """,
        (index_name,),
    ).fetchone()
    index_sql = str(index_sql_row[0] or "") if index_sql_row is not None else ""
    has_filter = re.search(
        r"where\s+status\s*!=\s*['\"]completed['\"]",
        index_sql,
        flags=re.IGNORECASE,
    )
    if columns != (
        "execution_ready",
        "status",
        "lease_expires_at",
        "updated_at",
        "operation_id",
    ) or has_filter is None:
        raise RuntimeError(
            "Memory forget-operation activation index has an unsupported schema"
        )


def _ensure_activation_schema(connection) -> None:
    columns = _column_rows(connection, "memory_forget_operations")
    if not columns:
        raise RuntimeError("Memory forget-operation table is missing")
    if "execution_ready" not in columns:
        connection.execute(_ADD_COLUMN_SQL)
    _validate_execution_ready_column(connection)
    connection.execute(_CREATE_INDEX_SQL)
    _validate_activation_index(connection)


def apply_sqlite(conn: sqlite3.Connection) -> None:
    _ensure_activation_schema(conn)


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""

    return SCHEMA_SQL


def upgrade() -> None:
    _ensure_activation_schema(op.get_bind().connection)


def downgrade() -> None:
    raise RuntimeError("Memory schema downgrades are not supported")


__all__ = [
    "SCHEMA_SQL",
    "apply_sqlite",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
