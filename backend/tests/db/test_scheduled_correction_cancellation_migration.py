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


@pytest.mark.parametrize("legacy", [False, True])
def test_cancellation_schema_paths_preserve_pending_and_cancelled_transitions(tmp_path, legacy):
    path = tmp_path / "memory.db"
    config = _memory_config(path)
    command.upgrade(
        config, "v16_relationship_correction_reconciliation" if legacy else V17_REVISION
    )
    with sqlite3.connect(path) as connection:
        if legacy:
            assert "transition_cancelled_at" not in {
                row[1] for row in connection.execute("PRAGMA table_info(memory_corrections)")
            }
        connection.execute(
            "INSERT INTO memory_corrections(correction_id,request_id,actor_id,target_kind,target_id,slot_key,claim_fingerprint,correction_kind,before_json,effective_at,state,created_at) VALUES ('future','request-future','user:u1','assertion','assertion-old','slot-location','claim-old','situation_changed','{}',200,'active',100)"
        )
    command.upgrade(config, V17_REVISION)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT correction_id,effective_at,transition_applied_at,transition_cancelled_at,transition_cancel_reason FROM memory_corrections"
        ).fetchall() == [("future", 200.0, None, None, None)]
        assert [
            row[2]
            for row in connection.execute(
                "PRAGMA index_info(idx_memory_corrections_due_transition)"
            )
        ] == [
            "correction_kind",
            "state",
            "transition_applied_at",
            "transition_cancelled_at",
            "effective_at",
        ]
        connection.execute(
            "UPDATE memory_corrections SET transition_cancelled_at=150,transition_cancel_reason='forget_entity' WHERE correction_id='future'"
        )
        before = connection.execute("SELECT * FROM memory_corrections").fetchall()
    with pytest.raises(RuntimeError, match="retained cancellations"):
        command.downgrade(config, "v16_relationship_correction_reconciliation")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM memory_corrections").fetchall() == before
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V17_REVISION,
        )
