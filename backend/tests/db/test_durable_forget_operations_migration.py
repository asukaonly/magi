from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.db.migrations.memory_shared.versions import (
    v27_durable_forget_operations as durable_forget_migration,
)

V26_REVISION = "v26_manual_entry_projection_intent"
V27_REVISION = "v27_durable_forget_operations"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_durable_forget_operation_schema_has_recovery_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V27_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V27_REVISION,
        )
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert "idx_memory_forget_operations_recovery" in indexes
        assert "idx_memory_forget_operation_events_pending" in indexes
        ref_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(memory_forget_operation_refs)"
            ).fetchall()
        }
        assert "ref_type" in ref_columns
        operation_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(memory_forget_operations)").fetchall()
        }
        assert "lease_token" in operation_columns
        assert "surface_finalized_at" in operation_columns
        assert "idx_memory_forget_operations_surface_recovery" in indexes
        l0_active_entity_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(l0_active_entities)").fetchall()
        }
        assert "source_event_ids" in l0_active_entity_columns
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'memory_entity_projection_identity_blocks'"
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'block_forgotten_episode_event_projection'"
            ).fetchone()
            is not None
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_empty_durable_forget_operation_migration_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V27_REVISION)
    command.downgrade(config, V26_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'memory_forget_operations'"
            ).fetchone()
            is None
        )
        l0_active_entity_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(l0_active_entities)").fetchall()
        }
        assert "source_event_ids" not in l0_active_entity_columns
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'block_forgotten_episode_event_projection'"
            ).fetchone()
            is None
        )


class _FailingMigrationConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._failed = False

    def execute(self, statement: str, *args):  # type: ignore[no-untyped-def]
        if not self._failed and "CREATE TABLE memory_forget_operation_events" in statement:
            self._failed = True
            raise sqlite3.OperationalError("simulated migration interruption")
        return self._connection.execute(statement, *args)


def test_durable_forget_migration_rolls_back_partial_failure_and_retries(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V26_REVISION)

    with sqlite3.connect(db_path) as connection:
        failing = _FailingMigrationConnection(connection)
        with pytest.raises(sqlite3.OperationalError, match="simulated migration"):
            durable_forget_migration._execute_script_atomically(
                failing,
                durable_forget_migration.SCHEMA_SQL,
                savepoint="test_v27_failure",
            )

        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'memory_forget_operations'"
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'memory_entity_projection_identity_blocks'"
            ).fetchone()
            is None
        )
        assert "source_event_ids" not in {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(l0_active_entities)").fetchall()
        }

        durable_forget_migration._execute_script_atomically(
            connection,
            durable_forget_migration.SCHEMA_SQL,
            savepoint="test_v27_retry",
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'memory_forget_operations'"
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'block_forgotten_episode_event_projection'"
            ).fetchone()
            is not None
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_durable_forget_operation_migration_refuses_history_loss(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V27_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES ('forget-1', 'known_events', 'hash', '{}', 'test', 1, 1)
            """)
        connection.commit()

    with pytest.raises(RuntimeError, match="while history exists"):
        command.downgrade(config, V26_REVISION)
