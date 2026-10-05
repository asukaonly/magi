from __future__ import annotations

import sqlite3

import pytest
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


FINAL_COLUMNS = {
    "id",
    "correlation_id",
    "channel_scope",
    "intent_fingerprint",
    "intent_json",
    "release_at_ms",
    "status",
    "created_at_ms",
}


def _channels_target():
    return next(
        target for target in MIGRATION_TARGETS if target.name == "channels"
    )


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(outreach_outbox)"
        ).fetchall()
    }


def _indexes(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            "PRAGMA index_list(outreach_outbox)"
        ).fetchall()
    }


@pytest.mark.parametrize("creation", ["baseline", "fresh_head", "legacy_upgrade"])
def test_outreach_schema_paths_enforce_channel_scoped_identity(
    tmp_path: Path,
    creation: str,
) -> None:
    target = _channels_target()
    db_path = tmp_path / "channels-legacy-v1.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")

    if creation == "legacy_upgrade":
        with sqlite3.connect(db_path) as connection:
            connection.execute("DROP INDEX uq_outreach_outbox_identity")
            connection.execute("DROP INDEX ix_outreach_outbox_due")
            connection.execute("DROP TABLE outreach_outbox")
            connection.execute("""
                CREATE TABLE outreach_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_json TEXT NOT NULL,
                    release_at_ms INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at_ms INTEGER NOT NULL
                )
                """)
            connection.execute("""
                CREATE INDEX ix_outreach_outbox_due
                ON outreach_outbox(status, release_at_ms)
                """)
            connection.execute("""
                INSERT INTO outreach_outbox(
                    intent_json,
                    release_at_ms,
                    status,
                    created_at_ms
                )
                VALUES ('{}', 1, 'pending', 1)
                """)
            connection.commit()

    if creation != "baseline":
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert _columns(connection) == FINAL_COLUMNS
        assert connection.execute("SELECT COUNT(*) FROM outreach_outbox").fetchone() == (0,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v1" if creation == "baseline" else "v2",
        )

        assert "uq_outreach_outbox_identity" in _indexes(connection)
        insert = "INSERT INTO outreach_outbox(correlation_id,channel_scope,intent_fingerprint,intent_json,release_at_ms,created_at_ms) VALUES (?,?,?,'{}',10,1)"
        connection.execute(insert, ("turn-1", "channel-a", "intent-original"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, ("turn-1", "channel-a", "intent-conflicting"))
        connection.execute(insert, ("turn-1", "channel-b", "intent-original"))
        connection.execute(insert, ("turn-2", "channel-a", "intent-original"))
        assert connection.execute(
            "SELECT correlation_id,channel_scope,intent_fingerprint FROM outreach_outbox ORDER BY correlation_id,channel_scope"
        ).fetchall() == [
            ("turn-1", "channel-a", "intent-original"),
            ("turn-1", "channel-b", "intent-original"),
            ("turn-2", "channel-a", "intent-original"),
        ]
