"""Removing the unused batch limit preserves job and item ownership."""

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_batch_limit_upgrade_and_downgrade_preserve_work(tmp_path: Path) -> None:
    path = tmp_path / "batch.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "batch")
    config = _build_config(target, path)
    command.upgrade(config, "v1")
    with sqlite3.connect(path) as db:
        db.execute(
            """INSERT INTO batch_job (
                job_id, title, owner, handler_ref, status, reconcile_rounds_max,
                created_at_ms, updated_at_ms
            ) VALUES ('job', 'Task', 'user', 'handler', 'running', 9, 1, 2)"""
        )
        db.execute(
            """INSERT INTO batch_item (
                job_id, item_id, status, attempts, lease_owner, lease_expires_at_ms, updated_at_ms
            ) VALUES ('job', 'item', 'running', 2, 'lease', 999, 2)"""
        )

    for revision in ("head", "v1", "head"):
        if revision == "v1":
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)
        with sqlite3.connect(path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(batch_job)")}
            assert ("reconcile_rounds_max" in columns) is (revision == "v1")
            assert db.execute(
                "SELECT job_id, title, owner, handler_ref, status FROM batch_job"
            ).fetchone() == ("job", "Task", "user", "handler", "running")
            assert db.execute(
                "SELECT job_id, item_id, status, attempts, lease_owner, lease_expires_at_ms FROM batch_item"
            ).fetchone() == ("job", "item", "running", 2, "lease", 999)
            assert "idx_batch_item_job_status" in {
                row[1] for row in db.execute("PRAGMA index_list(batch_item)")
            }
