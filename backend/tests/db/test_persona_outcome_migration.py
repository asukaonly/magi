"""Persona identity and outcome receipt migrations preserve existing state."""

import sqlite3

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_growth_upgrade_preserves_row_and_allows_same_user_for_two_personas(tmp_path):
    path = tmp_path / "growth.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "growth_memory")
    config = _build_config(target, path)
    command.upgrade(config, "v1")
    with sqlite3.connect(path) as db:
        db.execute("""INSERT INTO relationships VALUES (
            'user-a', 0.1, 1, 2, 3, '{}', 0, 0.5, '[]', 2, 'persona-a')""")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT total_interactions FROM relationships").fetchone() == (3,)
        db.execute("""INSERT INTO relationships VALUES (
            'user-a', 0.1, 1, 2, 4, '{}', 0, 0.5, '[]', 2, 'persona-b')""")
    with pytest.raises(RuntimeError, match="multiple personas"):
        command.downgrade(config, "v1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM relationships").fetchone() == (2,)
        db.execute("DELETE FROM relationships WHERE persona_id='persona-b'")
    command.downgrade(config, "v1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT total_interactions FROM relationships").fetchone() == (3,)
        assert db.execute("SELECT name FROM sqlite_master WHERE name='persona_outcome_receipts'").fetchone() is None


def test_emotional_receipt_upgrade_and_downgrade(tmp_path):
    path = tmp_path / "emotion.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "emotional")
    config = _build_config(target, path)
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO persona_outcome_receipts VALUES ('persona', 'outcome', 'interaction', 'user', 1)")
    command.downgrade(config, "v1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='persona_outcome_receipts'").fetchone() is None
