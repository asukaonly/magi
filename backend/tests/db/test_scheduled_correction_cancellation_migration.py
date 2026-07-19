"""Regression coverage for durable scheduled-correction cancellation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V17_REVISION = "v17_scheduled_correction_cancellation"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_cancellation_migration_upgrades_an_existing_v16_database(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v16_relationship_correction_reconciliation")

    with sqlite3.connect(db_path) as connection:
        before = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(memory_corrections)")
        }
    assert "transition_cancelled_at" not in before

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        after = {str(row[1]) for row in connection.execute("PRAGMA table_info(memory_corrections)")}
        index_columns = [
            str(row[2])
            for row in connection.execute(
                "PRAGMA index_info(idx_memory_corrections_due_transition)"
            )
        ]
    assert {"transition_cancelled_at", "transition_cancel_reason"} <= after
    assert index_columns == [
        "correction_kind",
        "state",
        "transition_applied_at",
        "transition_cancelled_at",
        "effective_at",
    ]


def test_cancellation_migration_refuses_to_drop_retained_cancellations(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V17_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                effective_at, state, created_at, transition_applied_at,
                transition_cancelled_at, transition_cancel_reason
            ) VALUES (
                'cancelled-future', 'cancelled-future-request', 'user:u1',
                'assertion', 'assertion-old', 'slot-location', 'claim-old',
                'situation_changed', '{}', 200, 'active', 100, NULL, 150,
                'forget_entity'
            )
            """)
        connection.commit()

    with pytest.raises(RuntimeError, match="retained cancellations"):
        command.downgrade(config, "v16_relationship_correction_reconciliation")

    with sqlite3.connect(db_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        retained = connection.execute("""
            SELECT transition_applied_at, transition_cancelled_at,
                   transition_cancel_reason
            FROM memory_corrections
            WHERE correction_id = 'cancelled-future'
            """).fetchone()
    assert revision == (V17_REVISION,)
    assert retained == (None, 150.0, "forget_entity")
