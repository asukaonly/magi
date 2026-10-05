"""Tests for removing control-less chat execution checkpoints from L0."""

from __future__ import annotations

import sqlite3

import pytest


def test_actual_upgrade_removes_only_retired_execution_state_and_cannot_restore_it(tmp_path):
    from alembic import command
    from magi.db.runner import MIGRATION_TARGETS, _build_config

    path = tmp_path / "memory.db"
    config = _build_config(
        next(target for target in MIGRATION_TARGETS if target.name == "memory_shared"), path
    )
    command.upgrade(config, "v33_chat_forget_activation")
    retired = ("l0_execution_runs", "l0_execution_pending_turns", "l0_execution_results")
    with sqlite3.connect(path) as connection:
        for table in retired:
            connection.execute(f"CREATE TABLE {table}(session_id TEXT PRIMARY KEY, payload TEXT)")
            connection.execute(
                f"INSERT INTO {table} VALUES ('session-ghost', 'obsolete execution')"
            )
        connection.execute(
            "INSERT INTO memory_forget_operations(operation_id,selector_kind,selector_hash,selector_json,reason,created_at,updated_at) VALUES ('keep-operation','known_events','hash','{}','keep',1,1)"
        )
        before = connection.execute("SELECT * FROM memory_forget_operations").fetchall()
    command.upgrade(config, "v34_remove_l0_execution_state")
    with pytest.raises(RuntimeError, match="checkpoints cannot be restored"):
        command.downgrade(config, "v33_chat_forget_activation")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM memory_forget_operations").fetchall() == before
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v34_remove_l0_execution_state",
        )
        for table in retired:
            assert (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                is None
            )
