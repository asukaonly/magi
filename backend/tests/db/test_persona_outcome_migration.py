"""Persona identity and outcome receipt migrations preserve existing state."""

import sqlite3

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config


pytestmark = pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning")


def _relationship_indexes(db):
    names = db.execute("""SELECT name FROM sqlite_master
        WHERE type='index' AND tbl_name='relationships' AND sql IS NOT NULL""").fetchall()
    return {name: db.execute(f"PRAGMA index_xinfo('{name}')").fetchall() for (name,) in names}


def _relationship_primary_key(db):
    columns = db.execute("PRAGMA table_info(relationships)").fetchall()
    return [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]


def test_growth_upgrade_preserves_row_and_allows_same_user_for_two_personas(tmp_path):
    path = tmp_path / "growth.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "growth_memory")
    config = _build_config(target, path)
    command.upgrade(config, "v1")
    with sqlite3.connect(path) as db:
        db.execute("""INSERT INTO relationships VALUES (
            'user-a', 0.1, 1, 2, 3, '{}', 0, 0.5, '[]', 2, 'persona-a')""")
        original_row = db.execute("SELECT * FROM relationships").fetchone()
        original_indexes = _relationship_indexes(db)
        assert set(original_indexes) == {"idx_relationships_updated", "idx_relationships_persona"}
        assert _relationship_primary_key(db) == ["user_id"]
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM relationships").fetchone() == original_row
        assert _relationship_indexes(db) == original_indexes
        assert _relationship_primary_key(db) == ["persona_id", "user_id"]
        db.execute("""INSERT INTO relationships VALUES (
            'user-a', 0.1, 1, 2, 4, '{}', 0, 0.5, '[]', 2, 'persona-b')""")
    with pytest.raises(RuntimeError, match="multiple personas"):
        command.downgrade(config, "v1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM relationships").fetchone() == (2,)
        db.execute("DELETE FROM relationships WHERE persona_id='persona-b'")
    command.downgrade(config, "v1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM relationships").fetchone() == original_row
        assert _relationship_indexes(db) == original_indexes
        assert _relationship_primary_key(db) == ["user_id"]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='persona_outcome_receipts'").fetchone() is None
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM relationships").fetchone() == original_row
        assert _relationship_indexes(db) == original_indexes
        assert _relationship_primary_key(db) == ["persona_id", "user_id"]


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
