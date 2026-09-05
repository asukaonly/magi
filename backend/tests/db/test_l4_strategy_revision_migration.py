"""Schema validation for versioned procedural strategy publication."""

import sqlite3

from alembic import command
from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_l4_strategy_revision_schema_is_available_at_release_head(tmp_path):
    path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    command.upgrade(_build_config(target, path), "head")
    with sqlite3.connect(path) as db:
        skill_columns = {row[1] for row in db.execute("PRAGMA table_info(procedural_skills)")}
        trace_columns = {row[1] for row in db.execute("PRAGMA table_info(l4_execution_traces)")}
        assert "strategy_revision" in skill_columns
        assert "strategy_processed_at" in trace_columns
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("v49_l4_strategy_revisions",)
