"""Older scheduler databases gain retry receipts without changing definitions."""

import sqlite3

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_existing_scheduler_upgrade_preserves_definitions(tmp_path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "scheduler")
    path = tmp_path / "scheduler.db"
    config = _build_config(target, path)
    command.upgrade(config, "v2")
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE schedule_creation_receipts")
        connection.execute("""
            INSERT INTO schedules VALUES ('existing', 'user_agent_task', 'existing',
            'interval', '{"seconds":60}', '{}', '{}', 1, 'existing', 10, 20)
        """)
    command.upgrade(config, "head")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT updated_at FROM schedules WHERE schedule_id = 'existing'").fetchone() == (20,)
        assert connection.execute("SELECT COUNT(*) FROM schedule_creation_receipts").fetchone() == (0,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v3",)
