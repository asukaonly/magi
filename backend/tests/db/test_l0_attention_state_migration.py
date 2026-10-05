"""Tests for replacing task-shaped L0 tables with attention state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
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


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [False, True])
async def test_v35_upgrade_preserves_legacy_forgetting_barriers(
    tmp_path: Path,
    fresh: bool,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V35_REVISION if fresh else V34_REVISION)
    source_table = (
        "l0_forgotten_attention_source_refs" if fresh else "l0_forgotten_tactic_source_refs"
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"""
            INSERT INTO {source_table}(source_ref, created_at)
            VALUES ('turn-forgotten', 123.5)
            """)
        connection.commit()

    command.upgrade(config, V35_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V35_REVISION,
        )
        assert connection.execute("""
            SELECT source_ref, created_at
            FROM l0_forgotten_attention_source_refs
            """).fetchall() == [("turn-forgotten", 123.5)]
        assert connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'l0_forgotten_tactic_source_refs'
            """).fetchone() is None

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "l0_attention_items",
            "l0_forgotten_attention_source_refs",
            "l0_forgotten_attention_entities",
            "memory_source_turn_cutoffs",
        } <= tables
        assert {
            "l0_goal_stack",
            "l0_active_entities",
            "l0_temporary_tactics",
            "l0_forgotten_tactic_source_refs",
        }.isdisjoint(tables)
        indexes = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert {
            "idx_l0_attention_session_status",
            "idx_l0_forgotten_attention_source_refs_created",
            "idx_l0_forgotten_attention_entities_cutoff",
            "idx_memory_source_turn_cutoffs_cutoff",
        } <= indexes
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
