"""Tests for removing control-less chat execution checkpoints from L0."""

from __future__ import annotations

import sqlite3

from magi.db.migrations.memory_shared.versions import (
    v34_remove_l0_execution_state as migration,
)


def test_v34_drops_legacy_execution_tables() -> None:
    connection = sqlite3.connect(":memory:")
    for table in (
        "l0_execution_runs",
        "l0_execution_pending_turns",
        "l0_execution_results",
    ):
        connection.execute(f"CREATE TABLE {table} (session_id TEXT PRIMARY KEY)")
        connection.execute(f"INSERT INTO {table} VALUES ('session-ghost')")

    connection.executescript(migration.DROP_SQL)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "l0_execution_runs",
        "l0_execution_pending_turns",
        "l0_execution_results",
    }.isdisjoint(tables)
