from __future__ import annotations

import sqlite3
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


def test_channels_v1_baseline_matches_outreach_identity_head(
    tmp_path: Path,
) -> None:
    target = _channels_target()
    v1_path = tmp_path / "channels-v1.db"
    head_path = tmp_path / "channels-head.db"

    v1_config = _build_config(target, v1_path)
    head_config = _build_config(target, head_path)
    command.upgrade(v1_config, "v1")
    command.upgrade(head_config, "head")

    with sqlite3.connect(v1_path) as v1, sqlite3.connect(head_path) as head:
        assert _columns(v1) == FINAL_COLUMNS
        assert _columns(head) == FINAL_COLUMNS
        assert _indexes(v1) == _indexes(head)
        assert "uq_outreach_outbox_identity" in _indexes(head)
        assert head.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v2",)


def test_channels_v2_discards_unidentifiable_legacy_pending_rows(
    tmp_path: Path,
) -> None:
    target = _channels_target()
    db_path = tmp_path / "channels-legacy-v1.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX uq_outreach_outbox_identity")
        connection.execute("DROP INDEX ix_outreach_outbox_due")
        connection.execute("DROP TABLE outreach_outbox")
        connection.execute(
            """
            CREATE TABLE outreach_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intent_json TEXT NOT NULL,
                release_at_ms INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at_ms INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX ix_outreach_outbox_due
            ON outreach_outbox(status, release_at_ms)
            """
        )
        connection.execute(
            """
            INSERT INTO outreach_outbox(
                intent_json,
                release_at_ms,
                status,
                created_at_ms
            )
            VALUES ('{}', 1, 'pending', 1)
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert _columns(connection) == FINAL_COLUMNS
        assert connection.execute(
            "SELECT COUNT(*) FROM outreach_outbox"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v2",)
