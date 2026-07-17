from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V22_REVISION = "v22_l4_source_event_links"
V23_REVISION = "v23_l0_tactic_source_tombstones"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_l0_tactic_source_tombstone_migration_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)

    command.upgrade(config, V22_REVISION)
    command.upgrade(config, V23_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V23_REVISION,
        )
        assert connection.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'l0_forgotten_tactic_source_refs'
            """).fetchone() == ("l0_forgotten_tactic_source_refs",)

    command.downgrade(config, V22_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'l0_forgotten_tactic_source_refs'
            """).fetchone() is None

    command.upgrade(config, V23_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V23_REVISION,
        )


def test_l0_tactic_source_tombstone_migration_refuses_data_loss(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V23_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO l0_forgotten_tactic_source_refs(source_ref, created_at)
            VALUES ('turn-forgotten', 1)
            """)
        connection.commit()

    with pytest.raises(RuntimeError, match="retained data"):
        command.downgrade(config, V22_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V23_REVISION,
        )
