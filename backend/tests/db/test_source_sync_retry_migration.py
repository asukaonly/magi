from __future__ import annotations

import sqlite3

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_scheduler_v1_upgrades_source_sync_jobs_for_durable_retries(tmp_path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "scheduler")
    db_path = tmp_path / "scheduler-v1.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX idx_source_sync_jobs_status_due_created")
        connection.execute("ALTER TABLE source_sync_jobs DROP COLUMN next_attempt_at")
        connection.execute("""
            CREATE INDEX idx_source_sync_jobs_status_created
            ON source_sync_jobs(status, created_at ASC)
            """)

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(source_sync_jobs)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(source_sync_jobs)")}
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()

    assert "next_attempt_at" in columns
    assert "idx_source_sync_jobs_status_due_created" in indexes
    assert "idx_source_sync_jobs_status_created" not in indexes
    assert revision == ("v2",)
