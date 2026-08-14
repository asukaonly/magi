from __future__ import annotations

import sqlite3

from magi.db.migrations.l1.versions.v3_unify_history_import_source import SCHEMA_SQL
from magi.db.migrations.l1.versions.v4_history_import_deletion_privacy import (
    SCHEMA_SQL as DELETION_PRIVACY_SQL,
)


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


def test_history_import_deletion_migration_purges_only_deleted_import_rows() -> None:
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(
            """
            CREATE TABLE fact_events(
                event_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                deleted_at REAL
            );
            CREATE TABLE l1_events_fts(event_id TEXT, content TEXT);
            CREATE TABLE l1_projected_event_entities(event_id TEXT);
            CREATE TABLE l1_event_entity_projection_state(event_id TEXT);
            CREATE TABLE l1_event_entities(event_id TEXT);
            CREATE TABLE l1_source_facets(event_id TEXT);
            CREATE TABLE l1_event_chunks(event_id TEXT);
            CREATE TABLE l1_event_embedding_state(event_id TEXT);
            CREATE TABLE l1_event_payload(event_id TEXT);
            """
        )
        db.executemany(
            "INSERT INTO fact_events(event_id, source, deleted_at) VALUES (?, ?, ?)",
            (
                ("deleted-import", "history_import", 1),
                ("active-import", "history_import", None),
                ("deleted-chat", "chat", 1),
            ),
        )
        for table in (
            "l1_events_fts",
            "l1_projected_event_entities",
            "l1_event_entity_projection_state",
            "l1_event_entities",
            "l1_source_facets",
            "l1_event_chunks",
            "l1_event_embedding_state",
            "l1_event_payload",
        ):
            db.executemany(
                f"INSERT INTO {table}(event_id) VALUES (?)",
                (("deleted-import",), ("active-import",), ("deleted-chat",)),
            )

        db.executescript(DELETION_PRIVACY_SQL)

        assert db.execute("SELECT event_id FROM fact_events ORDER BY event_id").fetchall() == [
            ("active-import",),
            ("deleted-chat",),
        ]
        for table in (
            "l1_events_fts",
            "l1_projected_event_entities",
            "l1_event_entity_projection_state",
            "l1_event_entities",
            "l1_source_facets",
            "l1_event_chunks",
            "l1_event_embedding_state",
            "l1_event_payload",
        ):
            assert db.execute(f"SELECT event_id FROM {table} ORDER BY event_id").fetchall() == [
                ("active-import",),
                ("deleted-chat",),
            ]
    finally:
        db.close()
