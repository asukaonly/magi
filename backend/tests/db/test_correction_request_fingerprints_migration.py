from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V29_REVISION = "v29_correction_revert_blocks"
V30_REVISION = "v30_correction_request_fingerprints"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_legacy_correction(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO memory_corrections(
            correction_id, request_id, actor_id, target_kind, target_id,
            slot_key, claim_fingerprint, correction_kind, before_json,
            state, created_at, transition_applied_at
        ) VALUES (
            'correction-1', 'request-1', 'user:self', 'assertion',
            'assertion-1', 'slot-1', 'claim-1', 'record_error', '{}',
            'active', 1, 1
        )
        """
    )


def test_request_fingerprint_migration_does_not_invent_legacy_intent(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V29_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_legacy_correction(connection)
        connection.commit()

    command.upgrade(config, V30_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_correction_request_fingerprints"
        ).fetchone() == (0,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_request_fingerprint_migration_round_trips_when_empty(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V30_REVISION)
    command.downgrade(config, V29_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table'
              AND name = 'memory_correction_request_fingerprints'
            """
            ).fetchone()
            is None
        )


def test_request_fingerprint_migration_refuses_identity_loss(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V30_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_legacy_correction(connection)
        connection.execute(
            """
            INSERT INTO memory_correction_request_fingerprints(
                correction_id, request_fingerprint, created_at
            ) VALUES ('correction-1', 'fingerprint-1', 1)
            """
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="while history exists"):
        command.downgrade(config, V29_REVISION)


def test_request_fingerprint_migration_allows_only_one_identity_per_correction(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V30_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_legacy_correction(connection)
        connection.execute(
            """
            INSERT INTO memory_correction_request_fingerprints(
                correction_id, request_fingerprint, created_at
            ) VALUES ('correction-1', 'v1:fingerprint-1', 1)
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_correction_request_fingerprints(
                    correction_id, request_fingerprint, created_at
                ) VALUES ('correction-1', 'v1:fingerprint-2', 2)
                """
            )
