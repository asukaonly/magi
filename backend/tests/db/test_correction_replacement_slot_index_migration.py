from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V30_REVISION = "v30_correction_request_fingerprints"
V31_REVISION = "v31_correction_replacement_slot_index"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_replacement_slot_index_migration_round_trips(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)

    command.upgrade(config, V31_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'index'
                  AND name = 'idx_memory_corrections_active_replacement_slot'
                """
            ).fetchone()
            is not None
        )

    command.downgrade(config, V30_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'index'
                  AND name = 'idx_memory_corrections_active_replacement_slot'
                """
            ).fetchone()
            is None
        )


def test_revert_block_lookup_uses_both_slot_indexes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    command.upgrade(_memory_config(db_path), V31_REVISION)

    with sqlite3.connect(db_path) as connection:
        before_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT correction_id
            FROM memory_corrections
            WHERE target_kind = 'edge'
              AND state = 'active'
              AND transition_cancelled_at IS NULL
              AND slot_key IN ('slot-a')
            """
        ).fetchall()
        replacement_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT correction_id
            FROM memory_corrections
            WHERE target_kind = 'edge'
              AND state = 'active'
              AND transition_cancelled_at IS NULL
              AND (
                  CASE WHEN json_valid(replacement_json)
                  THEN json_extract(replacement_json, '$.slot_key') END
              ) IN ('slot-a')
            """
        ).fetchall()

    assert any("idx_memory_corrections_slot_state" in str(row[3]) for row in before_plan)
    assert any(
        "idx_memory_corrections_active_replacement_slot" in str(row[3]) for row in replacement_plan
    )
