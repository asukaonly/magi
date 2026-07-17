from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V27_REVISION = "v27_durable_forget_operations"
V28_REVISION = "v28_time_range_forget_barriers"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_time_range_forget_barrier_schema_supports_hot_range_lookup(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V28_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V28_REVISION,
        )
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(memory_time_range_forget_barriers)"
            ).fetchall()
        }
        assert {
            "operation_id",
            "target_id",
            "selector_hash",
            "range_start",
            "range_end",
            "delete_l1_events",
            "reason",
            "created_at",
        } <= columns
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert "idx_memory_time_range_forget_barriers_match" in indexes
        query_plan = " ".join(str(value) for row in connection.execute("""
                EXPLAIN QUERY PLAN
                SELECT operation_id
                FROM memory_time_range_forget_barriers
                WHERE range_start <= 20 AND range_end >= 10
                """).fetchall() for value in row)
        assert "idx_memory_time_range_forget_barriers_match" in query_plan
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_time_range_forget_barrier_migration_backfills_existing_operations(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V27_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, status, phase, created_at, updated_at
            ) VALUES (?, 'time_range', ?, ?, ?, 'completed', 'completed', ?, ?)
            """,
            [
                (
                    "forget:existing-range-1",
                    "same-range-hash",
                    '{"start":10,"end":20,"delete_l1_events":false}',
                    "existing-retained-range",
                    1,
                    1,
                ),
                (
                    "forget:existing-range-2",
                    "same-range-hash",
                    '{"start":10,"end":20,"delete_l1_events":false}',
                    "existing-repeated-range",
                    2,
                    2,
                ),
            ],
        )
        connection.commit()

    command.upgrade(config, V28_REVISION)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("""
            SELECT operation_id, target_id, range_start, range_end,
                   delete_l1_events, reason
            FROM memory_time_range_forget_barriers
            ORDER BY operation_id
            """).fetchall()
    assert rows == [
        (
            "forget:existing-range-1",
            "time:same-range-hash:forget:existing-range-1",
            10.0,
            20.0,
            0,
            "existing-retained-range",
        ),
        (
            "forget:existing-range-2",
            "time:same-range-hash:forget:existing-range-2",
            10.0,
            20.0,
            0,
            "existing-repeated-range",
        ),
    ]


def test_empty_time_range_forget_barrier_migration_round_trips(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V28_REVISION)
    command.downgrade(config, V27_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'memory_time_range_forget_barriers'
                """).fetchone() is None


def test_time_range_forget_barrier_migration_refuses_history_loss(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V28_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (
                'forget-range-1', 'time_range', 'range-hash',
                '{"start":10,"end":20,"delete_l1_events":false}',
                'test', 1, 1
            )
            """)
        connection.execute("""
            INSERT INTO memory_time_range_forget_barriers(
                operation_id, target_id, selector_hash, range_start, range_end,
                delete_l1_events, reason, created_at
            ) VALUES (
                'forget-range-1', 'time:range-hash:1', 'range-hash',
                10, 20, 0, 'test', 1
            )
            """)
        connection.commit()

    with pytest.raises(RuntimeError, match="while history exists"):
        command.downgrade(config, V27_REVISION)
