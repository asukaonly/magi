"""Native query indexes must remain valid portable database schema."""
from pathlib import Path
import sqlite3

import pytest

from magi.db.runner import migration_head, run_upgrade_database
from magi.memory.portability.preflight import _validate_schema_against_revision


@pytest.mark.parametrize('target,indexes', [
    ('l1', {'idx_fact_events_deleted_at'}),
    ('memory_shared', {'idx_kg_status_updated', 'idx_tom_assertions_updated', 'idx_summaries_updated'}),
])
def test_native_read_indexes_are_migrated_and_pass_restore_validation(tmp_path: Path, target: str, indexes: set[str]) -> None:
    path = tmp_path / 'memory.db'
    run_upgrade_database(target, path, revision='head')
    with sqlite3.connect(path) as connection:
        present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert indexes <= present
    _validate_schema_against_revision(path, target_name=target, revision=migration_head(target))
