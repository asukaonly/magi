from __future__ import annotations

import sqlite3

from magi.db.migrations.l1.versions.v3_unify_history_import_source import SCHEMA_SQL


def test_history_import_source_migration_updates_existing_l1_rows() -> None:
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE fact_events(event_id TEXT PRIMARY KEY, source TEXT NOT NULL)")
        db.execute(
            "INSERT INTO fact_events(event_id, source) VALUES (?, ?)",
            ("event-1", "history_import_markdown"),
        )

        db.executescript(SCHEMA_SQL)

        assert db.execute("SELECT source FROM fact_events").fetchone()[0] == "history_import"
    finally:
        db.close()
