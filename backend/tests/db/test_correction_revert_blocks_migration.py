from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V28_REVISION = "v28_time_range_forget_barriers"
V29_REVISION = "v29_correction_revert_blocks"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_correction(
    connection: sqlite3.Connection,
    *,
    correction_id: str,
    target_id: str,
    replacement_target_id: str,
    created_at: float,
    slot_key: str = "shared-slot",
    replacement_slot_key: str | None = None,
) -> None:
    before_json = json.dumps(
        {"slot_key": slot_key, "scope_json": "{}"},
        separators=(",", ":"),
    )
    replacement_json = json.dumps(
        {
            "slot_key": replacement_slot_key or slot_key,
            "scope_json": "{}",
        },
        separators=(",", ":"),
    )
    connection.execute(
        """
        INSERT INTO memory_corrections(
            correction_id, request_id, actor_id, target_kind, target_id,
            slot_key, claim_fingerprint, correction_kind, before_json,
            replacement_json, replacement_target_id, state, created_at,
            transition_applied_at
        ) VALUES (?, ?, 'user:self', 'assertion', ?, ?, ?,
                  'record_error', ?, ?, ?, 'active', ?, ?)
        """,
        (
            correction_id,
            f"request-{correction_id}",
            target_id,
            slot_key,
            f"claim-{correction_id}",
            before_json,
            replacement_json,
            replacement_target_id,
            created_at,
            created_at,
        ),
    )


def test_correction_revert_block_migration_round_trips_when_empty(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)

    command.upgrade(config, V29_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V29_REVISION,
        )
        assert (
            connection.execute(
                """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'memory_correction_revert_blocks'
            """
            ).fetchone()
            is not None
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    command.downgrade(config, V28_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'memory_correction_revert_blocks'
            """
            ).fetchone()
            is None
        )


def test_correction_revert_block_migration_refuses_history_loss(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V29_REVISION)
    with sqlite3.connect(db_path) as connection:
        correction = connection.execute(
            "SELECT correction_id FROM memory_corrections LIMIT 1"
        ).fetchone()
        if correction is None:
            connection.execute(
                """
                INSERT INTO memory_corrections(
                    correction_id, request_id, actor_id, target_kind, target_id,
                    slot_key, claim_fingerprint, correction_kind, before_json,
                    state, created_at, transition_applied_at
                ) VALUES (
                    'correction-1', 'request-1', 'user:self', 'assertion',
                    'assertion-1', 'slot-1', 'claim-1', 'record_error', '{}',
                    'active', 1, 1
                )
                """
            )
            correction_id = "correction-1"
        else:
            correction_id = str(correction[0])
        connection.execute(
            """
            INSERT INTO memory_correction_revert_blocks(
                correction_id, block_reason, created_at
            ) VALUES (?, 'identity_merge', 1)
            """,
            (correction_id,),
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="while history exists"):
        command.downgrade(config, V28_REVISION)


def test_correction_revert_block_migration_backfills_parallel_lineages(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V28_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_correction(
            connection,
            correction_id="parallel-1",
            target_id="assertion-a",
            replacement_target_id="assertion-b",
            created_at=1,
        )
        _insert_correction(
            connection,
            correction_id="parallel-2",
            target_id="assertion-c",
            replacement_target_id="assertion-d",
            created_at=2,
        )
        connection.commit()

    command.upgrade(config, V29_REVISION)

    with sqlite3.connect(db_path) as connection:
        blocked = connection.execute(
            """
            SELECT correction_id, block_reason
            FROM memory_correction_revert_blocks
            ORDER BY correction_id
            """
        ).fetchall()
    assert blocked == [
        ("parallel-1", "lineage_collision"),
        ("parallel-2", "lineage_collision"),
    ]


def test_correction_revert_block_migration_keeps_one_continuous_lineage_revertible(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V28_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_correction(
            connection,
            correction_id="chain-1",
            target_id="assertion-a",
            replacement_target_id="assertion-b",
            created_at=1,
        )
        _insert_correction(
            connection,
            correction_id="chain-2",
            target_id="assertion-b",
            replacement_target_id="assertion-c",
            created_at=2,
        )
        connection.commit()

    command.upgrade(config, V29_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_correction_revert_blocks"
        ).fetchone() == (0,)


def test_correction_revert_block_migration_blocks_a_forked_lineage(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V28_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_correction(
            connection,
            correction_id="fork-root",
            target_id="assertion-a",
            replacement_target_id="assertion-b",
            created_at=1,
        )
        _insert_correction(
            connection,
            correction_id="fork-left",
            target_id="assertion-b",
            replacement_target_id="assertion-c",
            created_at=2,
        )
        _insert_correction(
            connection,
            correction_id="fork-right",
            target_id="assertion-b",
            replacement_target_id="assertion-d",
            created_at=3,
        )
        connection.commit()

    command.upgrade(config, V29_REVISION)

    with sqlite3.connect(db_path) as connection:
        blocked = connection.execute(
            """
            SELECT correction_id
            FROM memory_correction_revert_blocks
            ORDER BY correction_id
            """
        ).fetchall()
    assert blocked == [
        ("fork-left",),
        ("fork-right",),
        ("fork-root",),
    ]


def test_correction_revert_block_migration_uses_shared_replacement_slot(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V28_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_correction(
            connection,
            correction_id="replacement-left",
            target_id="assertion-a",
            replacement_target_id="assertion-shared",
            created_at=1,
            slot_key="before-left",
            replacement_slot_key="shared-output",
        )
        _insert_correction(
            connection,
            correction_id="replacement-right",
            target_id="assertion-b",
            replacement_target_id="assertion-shared",
            created_at=2,
            slot_key="before-right",
            replacement_slot_key="shared-output",
        )
        connection.commit()

    command.upgrade(config, V29_REVISION)

    with sqlite3.connect(db_path) as connection:
        blocked = connection.execute(
            """
            SELECT correction_id
            FROM memory_correction_revert_blocks
            ORDER BY correction_id
            """
        ).fetchall()
    assert blocked == [
        ("replacement-left",),
        ("replacement-right",),
    ]
