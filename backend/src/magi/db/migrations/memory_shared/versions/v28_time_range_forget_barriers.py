"""Persist durable time-range forget barriers.

Revision ID: v28_time_range_forget_barriers
Revises: v27_durable_forget_operations
"""

from __future__ import annotations

import json
import math
import sqlite3

from alembic import op

revision = "v28_time_range_forget_barriers"
down_revision = "v27_durable_forget_operations"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE memory_time_range_forget_barriers (
    operation_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL UNIQUE CHECK(
        TRIM(target_id) != '' AND target_id LIKE 'time:%'
    ),
    selector_hash TEXT NOT NULL CHECK(TRIM(selector_hash) != ''),
    range_start REAL NOT NULL,
    range_end REAL NOT NULL CHECK(range_end > range_start),
    delete_l1_events INTEGER NOT NULL CHECK(delete_l1_events IN (0, 1)),
    reason TEXT NOT NULL CHECK(TRIM(reason) != ''),
    created_at REAL NOT NULL,
    FOREIGN KEY(operation_id) REFERENCES memory_forget_operations(operation_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_memory_time_range_forget_barriers_match
    ON memory_time_range_forget_barriers(
        range_start, range_end, delete_l1_events, operation_id
    );
CREATE INDEX idx_memory_time_range_forget_barriers_selector
    ON memory_time_range_forget_barriers(
        selector_hash, created_at, operation_id
    );
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_time_range_forget_barriers_selector;
DROP INDEX IF EXISTS idx_memory_time_range_forget_barriers_match;
DROP TABLE IF EXISTS memory_time_range_forget_barriers;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a new shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    savepoint = "v28_time_range_forget_barriers"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        for statement in _statements(SCHEMA_SQL):
            connection.execute(statement)
        _backfill_existing_time_range_operations(connection)
    except Exception:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def downgrade() -> None:
    connection = op.get_bind().connection
    retained = connection.execute(
        "SELECT COUNT(*) FROM memory_time_range_forget_barriers"
    ).fetchone()
    if retained is not None and int(retained[0]) > 0:
        raise RuntimeError("Cannot downgrade time-range forget barriers while history exists")
    _execute_script_atomically(
        connection,
        DROP_SQL,
        savepoint="v28_time_range_forget_barriers_down",
    )


def _execute_script_atomically(connection, script: str, *, savepoint: str) -> None:
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        for statement in _statements(script):
            connection.execute(statement)
    except Exception:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def _backfill_existing_time_range_operations(connection) -> None:
    rows = connection.execute("""
        SELECT operation_id, selector_hash, selector_json, reason, created_at
        FROM memory_forget_operations
        WHERE selector_kind = 'time_range'
        ORDER BY created_at, operation_id
        """).fetchall()
    for operation_id, selector_hash, selector_json, reason, created_at in rows:
        try:
            payload = json.loads(str(selector_json))
            range_start = float(payload["start"])
            range_end = float(payload["end"])
            delete_l1_events = payload["delete_l1_events"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Cannot recover time-range forget operation {operation_id}"
            ) from exc
        if (
            not isinstance(payload, dict)
            or not math.isfinite(range_start)
            or not math.isfinite(range_end)
            or range_end <= range_start
            or not isinstance(delete_l1_events, bool)
        ):
            raise RuntimeError(f"Cannot recover time-range forget operation {operation_id}")
        connection.execute(
            """
            INSERT INTO memory_time_range_forget_barriers(
                operation_id, target_id, selector_hash, range_start, range_end,
                delete_l1_events, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(operation_id),
                f"time:{selector_hash}:{operation_id}",
                str(selector_hash),
                range_start,
                range_end,
                int(delete_l1_events),
                str(reason),
                float(created_at),
            ),
        )


def _statements(script: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                statements.append(statement)
            pending = ""
    if pending.strip():
        raise ValueError("Incomplete SQLite migration statement")
    return statements


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
