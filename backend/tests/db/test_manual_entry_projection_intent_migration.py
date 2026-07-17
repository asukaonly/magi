from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V25_REVISION = "v25_daily_mood_source_events"
V26_REVISION = "v26_manual_entry_projection_intent"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_manual_entry(connection: sqlite3.Connection) -> None:
    connection.execute("""
        INSERT INTO manual_entries(
            entry_id, created_at, event_at, kind, body
        ) VALUES ('manual-1', 1, 1, 'quick', 'hello')
        """)
    connection.commit()


def test_manual_entry_projection_intent_migration_preserves_source_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V25_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_manual_entry(connection)

    command.upgrade(config, V26_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V26_REVISION,
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(manual_entries)")}
        assert {
            "pending_l1_event_id",
            "pending_l1_predecessor_event_id",
            "delete_requested_at",
        } <= columns
        assert connection.execute(
            "SELECT body, pending_l1_event_id FROM manual_entries WHERE entry_id = 'manual-1'"
        ).fetchone() == ("hello", None)
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(manual_entries)")}
        assert "idx_manual_entries_pending_l1_event" in indexes
        assert "idx_manual_entries_recovery_pending" in indexes
        recovery_index_sql = connection.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_manual_entries_recovery_pending'
            """).fetchone()[0]
        assert "ON manual_entries(entry_id)" in recovery_index_sql
        assert "OR l1_event_id IS NULL" in recovery_index_sql


def test_manual_entry_projection_intent_empty_migration_round_trips(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V26_REVISION)
    command.downgrade(config, V25_REVISION)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(manual_entries)")}
        assert "pending_l1_event_id" not in columns
        assert "pending_l1_predecessor_event_id" not in columns
        assert "delete_requested_at" not in columns


@pytest.mark.parametrize("reserve_pending_projection", [False, True])
def test_manual_entry_projection_intent_refuses_to_drop_recovery_state(
    tmp_path: Path,
    reserve_pending_projection: bool,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V26_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_manual_entry(connection)
        if reserve_pending_projection:
            connection.execute("""
                UPDATE manual_entries
                SET pending_l1_event_id = 'event-new'
                WHERE entry_id = 'manual-1'
                """)
        connection.commit()

    with pytest.raises(RuntimeError, match="recovery is pending"):
        command.downgrade(config, V25_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V26_REVISION,
        )
