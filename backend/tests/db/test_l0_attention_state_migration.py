"""Tests for replacing task-shaped L0 tables with attention state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from magi.db.migrations.memory_shared.versions import (
    v35_l0_attention_state as migration,
)
from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.l0.working_memory import L0WorkingMemoryStore

V34_REVISION = "v34_remove_l0_execution_state"
V35_REVISION = "v35_l0_attention_state"


def _memory_config(db_path: Path):
    target = next(
        item for item in MIGRATION_TARGETS if item.name == "memory_shared"
    )
    return _build_config(target, db_path)


def test_v35_creates_attention_tables_and_drops_legacy_l0_tables() -> None:
    connection = sqlite3.connect(":memory:")
    for table in ("l0_goal_stack", "l0_active_entities", "l0_temporary_tactics"):
        connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
    connection.execute(
        """
        CREATE TABLE l0_forgotten_tactic_source_refs (
            source_ref TEXT PRIMARY KEY,
            created_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO l0_forgotten_tactic_source_refs(source_ref, created_at)
        VALUES ('turn-forgotten', 123.5)
        """
    )

    connection.executescript(migration.schema_sql_for_fresh_database())

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "l0_attention_items",
        "l0_forgotten_attention_source_refs",
        "l0_forgotten_attention_entities",
        "memory_source_turn_cutoffs",
    }.issubset(tables)
    assert {
        "l0_goal_stack",
        "l0_active_entities",
        "l0_temporary_tactics",
        "l0_forgotten_tactic_source_refs",
    }.isdisjoint(tables)

    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert "idx_l0_attention_session_status" in indexes
    assert "idx_l0_forgotten_attention_source_refs_created" in indexes
    assert "idx_l0_forgotten_attention_entities_cutoff" in indexes
    assert "idx_memory_source_turn_cutoffs_cutoff" in indexes
    assert connection.execute(
        """
        SELECT source_ref, created_at
        FROM l0_forgotten_attention_source_refs
        """
    ).fetchall() == [("turn-forgotten", 123.5)]


@pytest.mark.asyncio
async def test_v35_upgrade_preserves_legacy_forgetting_barriers(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V34_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO l0_forgotten_tactic_source_refs(source_ref, created_at)
            VALUES ('turn-forgotten', 123.5)
            """
        )
        connection.commit()

    command.upgrade(config, V35_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (V35_REVISION,)
        assert connection.execute(
            """
            SELECT source_ref, created_at
            FROM l0_forgotten_attention_source_refs
            """
        ).fetchall() == [("turn-forgotten", 123.5)]
        assert connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'l0_forgotten_tactic_source_refs'
            """
        ).fetchone() is None

    store = L0WorkingMemoryStore(checkpoint_db_path=str(db_path))
    try:
        replay = await store.apply_attention_actions(
            session_id="session-1",
            actions=(
                AttentionUpdateAction(
                    action=AttentionActionType.ADD,
                    kind=AttentionKind.FOCUS,
                    summary="Legacy forgotten turn must stay blocked",
                    source_turn_ids=("turn-forgotten",),
                ),
            ),
            expected_revision=0,
            last_processed_turn_id="turn-forgotten",
            source_turn_accepted_at={"turn-forgotten": 999.0},
        )
        assert replay is not None
        assert replay["items"] == []
    finally:
        await store.shutdown()
