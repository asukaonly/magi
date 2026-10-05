from __future__ import annotations

import sqlite3

from magi.db.migrations.l1.versions.v4_history_import_deletion_privacy import (
    SCHEMA_SQL as DELETION_PRIVACY_SQL,
)


def test_history_import_upgrade_changes_only_the_legacy_source(tmp_path):
    from alembic import command
    from magi.db.runner import MIGRATION_TARGETS, _build_config

    target = next(target for target in MIGRATION_TARGETS if target.name == "l1")
    path = tmp_path / "l1.db"
    config = _build_config(target, path)
    command.upgrade(config, "v2_l2_entity_link_projections")
    rows = [
        ("legacy", "history_import_markdown"),
        ("unified", "history_import"),
        ("chat", "chat"),
        ("plugin", "calendar"),
    ]
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO fact_events(event_id,timestamp,created_at,event_type,source,memory_domain,content,author_type,content_type) VALUES (?,1,2,'history_import.document',?,1,'preserved content',1,1)",
            rows,
        )
        before = connection.execute(
            "SELECT event_id,timestamp,created_at,event_type,memory_domain,content,author_type,content_type FROM fact_events ORDER BY event_id"
        ).fetchall()
    command.upgrade(config, "v3_unify_history_import_source")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT event_id,source FROM fact_events ORDER BY event_id"
        ).fetchall() == [
            ("chat", "chat"),
            ("legacy", "history_import"),
            ("plugin", "calendar"),
            ("unified", "history_import"),
        ]
        assert (
            connection.execute(
                "SELECT event_id,timestamp,created_at,event_type,memory_domain,content,author_type,content_type FROM fact_events ORDER BY event_id"
            ).fetchall()
            == before
        )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v3_unify_history_import_source",
        )


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
