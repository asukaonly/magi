"""Message-queue delivery-attempt schema migration coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.db.migrations.message_queue.versions import (
    v5_user_message_delivery_attempts as delivery_attempt_migration,
)


def _message_queue_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "message_queue")
    return _build_config(target, db_path)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _prepare_v4_queue(db_path: Path) -> int:
    config = _message_queue_config(db_path)
    command.upgrade(config, "v4")
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE runtime_commands DROP COLUMN delivery_attempt_no")
        conn.execute(
            "ALTER TABLE runtime_user_message_idempotency "
            "RENAME TO runtime_user_message_idempotency_current"
        )
        conn.execute(delivery_attempt_migration._LEGACY_RECEIPT_SCHEMA)
        conn.execute("DROP TABLE runtime_user_message_idempotency_current")
        command_id = conn.execute(
            """
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status, retry_count,
                user_message_generation, created_at, updated_at
            ) VALUES (
                'user_message', '{"message":"preserve me"}',
                'user_message:message-resume', 'claimed', 2, 0, 10, 11
            )
            """
        ).lastrowid
        assert command_id is not None
        conn.execute(
            """
            INSERT INTO runtime_user_message_idempotency (
                correlation_id, payload_fingerprint, first_command_id,
                delivery_status, created_at
            ) VALUES (
                'user_message:message-resume', 'fingerprint-resume',
                ?, 'open', 10
            )
            """,
            (command_id,),
        )
        conn.commit()
    return int(command_id)


def test_message_queue_v1_baseline_uses_attempt_aware_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "message-queue-v1.db"
    config = _message_queue_config(db_path)

    command.upgrade(config, "v1")

    with sqlite3.connect(db_path) as conn:
        assert "delivery_attempt_no" in _columns(conn, "runtime_commands")
        receipt_columns = _columns(conn, "runtime_user_message_idempotency")
        assert "current_attempt_no" in receipt_columns
        assert "current_command_id" in receipt_columns
        assert "first_command_id" not in receipt_columns

    command.upgrade(config, "head")


def test_message_queue_v5_preserves_v4_receipts_and_commands(tmp_path: Path) -> None:
    db_path = tmp_path / "message-queue-v4.db"
    config = _message_queue_config(db_path)
    command.upgrade(config, "v4")

    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE runtime_commands DROP COLUMN delivery_attempt_no")
        conn.execute(
            "ALTER TABLE runtime_user_message_idempotency "
            "RENAME TO runtime_user_message_idempotency_new"
        )
        conn.execute(
            """
            CREATE TABLE runtime_user_message_idempotency (
                correlation_id TEXT PRIMARY KEY,
                payload_fingerprint TEXT NOT NULL,
                first_command_id INTEGER NOT NULL,
                delivery_status TEXT NOT NULL DEFAULT 'open',
                created_at REAL NOT NULL
            )
            """
        )
        command_id = conn.execute(
            """
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status, retry_count,
                user_message_generation, created_at, updated_at
            ) VALUES (
                'user_message', '{"message":"preserve me"}',
                'user_message:message-1', 'claimed', 2, 0, 10, 11
            )
            """
        ).lastrowid
        conn.execute(
            """
            INSERT INTO runtime_user_message_idempotency (
                correlation_id, payload_fingerprint, first_command_id,
                delivery_status, created_at
            ) VALUES ('user_message:message-1', 'fingerprint', ?, 'open', 10)
            """,
            (command_id,),
        )
        conn.execute("DROP TABLE runtime_user_message_idempotency_new")
        conn.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT command_id, delivery_attempt_no, payload_json, status, retry_count
            FROM runtime_commands
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone() == (
            command_id,
            0,
            '{"message":"preserve me"}',
            "claimed",
            2,
        )
        assert conn.execute(
            """
            SELECT correlation_id, payload_fingerprint, current_attempt_no,
                   current_command_id, delivery_status, created_at
            FROM runtime_user_message_idempotency
            """
        ).fetchone() == (
            "user_message:message-1",
            "fingerprint",
            0,
            command_id,
            "open",
            10.0,
        )


@pytest.mark.parametrize(
    "interruption",
    ["rename_only", "create_before_copy", "copy_before_drop"],
)
def test_message_queue_v5_upgrade_resumes_each_receipt_rebuild_boundary(
    tmp_path: Path,
    interruption: str,
) -> None:
    db_path = tmp_path / f"message-queue-{interruption}.db"
    config = _message_queue_config(db_path)
    command_id = _prepare_v4_queue(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            ALTER TABLE runtime_commands
            ADD COLUMN delivery_attempt_no INTEGER NOT NULL DEFAULT 0
                CHECK (delivery_attempt_no >= 0)
            """
        )
        conn.execute(
            "ALTER TABLE runtime_user_message_idempotency "
            "RENAME TO runtime_user_message_idempotency_v4"
        )
        if interruption != "rename_only":
            conn.execute(delivery_attempt_migration._CURRENT_RECEIPT_SCHEMA)
        if interruption == "copy_before_drop":
            delivery_attempt_migration._copy_legacy_receipts(conn)
        conn.commit()

    command.upgrade(config, "head")
    expected_head = ScriptDirectory.from_config(config).get_current_head()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT correlation_id, payload_fingerprint, current_attempt_no,
                   current_command_id, delivery_status, created_at
            FROM runtime_user_message_idempotency
            """
        ).fetchone() == (
            "user_message:message-resume",
            "fingerprint-resume",
            0,
            command_id,
            "open",
            10.0,
        )
        assert conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table'
              AND name = 'runtime_user_message_idempotency_v4'
            """
        ).fetchone() is None
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (expected_head,)


def test_message_queue_v5_upgrade_fails_closed_on_receipt_conflict(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "message-queue-upgrade-conflict.db"
    config = _message_queue_config(db_path)
    command_id = _prepare_v4_queue(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            ALTER TABLE runtime_commands
            ADD COLUMN delivery_attempt_no INTEGER NOT NULL DEFAULT 0
                CHECK (delivery_attempt_no >= 0)
            """
        )
        conn.execute(
            "ALTER TABLE runtime_user_message_idempotency "
            "RENAME TO runtime_user_message_idempotency_v4"
        )
        conn.execute(delivery_attempt_migration._CURRENT_RECEIPT_SCHEMA)
        conn.execute(
            """
            INSERT INTO runtime_user_message_idempotency (
                correlation_id, payload_fingerprint, current_attempt_no,
                current_command_id, delivery_status, created_at
            ) VALUES (
                'user_message:message-resume', 'conflicting-fingerprint',
                0, ?, 'open', 10
            )
            """,
            (command_id,),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="could not preserve legacy row"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name LIKE 'runtime_user_message_idempotency%'
                """
            )
        }
        assert {
            "runtime_user_message_idempotency",
            "runtime_user_message_idempotency_v4",
        } <= tables
        assert conn.execute(
            """
            SELECT payload_fingerprint
            FROM runtime_user_message_idempotency_v4
            WHERE correlation_id = 'user_message:message-resume'
            """
        ).fetchone() == ("fingerprint-resume",)
        assert conn.execute(
            """
            SELECT payload_fingerprint
            FROM runtime_user_message_idempotency
            WHERE correlation_id = 'user_message:message-resume'
            """
        ).fetchone() == ("conflicting-fingerprint",)
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v4",)


def test_message_queue_v5_upgrade_rejects_attempt_column_without_constraint(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "message-queue-invalid-attempt-schema.db"
    config = _message_queue_config(db_path)
    _prepare_v4_queue(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            ALTER TABLE runtime_commands
            ADD COLUMN delivery_attempt_no INTEGER NOT NULL DEFAULT 0
            """
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="unsupported schema"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT payload_fingerprint
            FROM runtime_user_message_idempotency
            WHERE correlation_id = 'user_message:message-resume'
            """
        ).fetchone() == ("fingerprint-resume",)
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v4",)


def _prepare_v5_queue(db_path: Path) -> int:
    config = _message_queue_config(db_path)
    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as conn:
        command_id = conn.execute(
            """
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status, retry_count,
                user_message_generation, delivery_attempt_no,
                created_at, updated_at
            ) VALUES (
                'user_message', '{"message":"preserve me"}',
                'user_message:message-downgrade', 'claimed', 2, 4, 3, 10, 11
            )
            """
        ).lastrowid
        assert command_id is not None
        conn.execute(
            """
            INSERT INTO runtime_user_message_idempotency (
                correlation_id, payload_fingerprint, current_attempt_no,
                current_command_id, delivery_status, created_at
            ) VALUES (
                'user_message:message-downgrade', 'fingerprint-downgrade',
                3, ?, 'open', 10
            )
            """,
            (command_id,),
        )
        conn.commit()
    return int(command_id)


@pytest.mark.parametrize(
    "interruption",
    [
        "receipt_rename_only",
        "receipt_create_before_copy",
        "receipt_copy_before_drop",
        "command_rename_only",
        "command_create_before_copy",
        "command_copy_before_drop",
    ],
)
def test_message_queue_v5_downgrade_resumes_each_table_rebuild_boundary(
    tmp_path: Path,
    interruption: str,
) -> None:
    db_path = tmp_path / f"message-queue-downgrade-{interruption}.db"
    config = _message_queue_config(db_path)
    command_id = _prepare_v5_queue(db_path)

    with sqlite3.connect(db_path) as conn:
        if interruption.startswith("receipt_"):
            conn.execute(
                "ALTER TABLE runtime_user_message_idempotency "
                "RENAME TO runtime_user_message_idempotency_v5"
            )
            if interruption != "receipt_rename_only":
                conn.execute(delivery_attempt_migration._LEGACY_RECEIPT_SCHEMA)
            if interruption == "receipt_copy_before_drop":
                delivery_attempt_migration._copy_current_receipts_to_legacy(conn)
        else:
            delivery_attempt_migration._downgrade_receipts(conn)
            for index_name in (
                "idx_runtime_commands_status_created",
                "idx_runtime_commands_type_status_created",
                "idx_runtime_commands_user_message_generation",
            ):
                conn.execute(f"DROP INDEX IF EXISTS {index_name}")
            conn.execute(
                "ALTER TABLE runtime_commands RENAME TO runtime_commands_v5"
            )
            if interruption != "command_rename_only":
                conn.execute(delivery_attempt_migration._LEGACY_COMMAND_SCHEMA)
            if interruption == "command_copy_before_drop":
                delivery_attempt_migration._copy_current_commands_to_legacy(conn)
        conn.commit()

    command.downgrade(config, "v4")

    with sqlite3.connect(db_path) as conn:
        assert "delivery_attempt_no" not in _columns(conn, "runtime_commands")
        assert conn.execute(
            """
            SELECT command_id, command_type, payload_json, correlation_id,
                   status, retry_count, user_message_generation,
                   created_at, updated_at
            FROM runtime_commands
            """
        ).fetchone() == (
            command_id,
            "user_message",
            '{"message":"preserve me"}',
            "user_message:message-downgrade",
            "claimed",
            2,
            4,
            10.0,
            11.0,
        )
        assert conn.execute(
            """
            SELECT correlation_id, payload_fingerprint, first_command_id,
                   delivery_status, created_at
            FROM runtime_user_message_idempotency
            """
        ).fetchone() == (
            "user_message:message-downgrade",
            "fingerprint-downgrade",
            command_id,
            "open",
            10.0,
        )
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                  'runtime_user_message_idempotency_v5',
                  'runtime_commands_v5'
              )
            """
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v4",)
        indexes = {
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                  AND name LIKE 'idx_runtime_commands_%'
                """
            )
        }
        assert {
            "idx_runtime_commands_status_created",
            "idx_runtime_commands_type_status_created",
            "idx_runtime_commands_user_message_generation",
        } <= indexes
        next_command_id = conn.execute(
            """
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status, retry_count,
                user_message_generation, created_at, updated_at
            ) VALUES (
                'refresh_llm_config', '{}', 'refresh-after-downgrade',
                'pending', 0, 0, 12, 12
            )
            """
        ).lastrowid
        assert next_command_id is not None
        assert int(next_command_id) > command_id
        conn.commit()

    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT delivery_attempt_no
            FROM runtime_commands
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone() == (0,)
        assert conn.execute(
            """
            SELECT current_attempt_no, current_command_id
            FROM runtime_user_message_idempotency
            """
        ).fetchone() == (0, command_id)


def test_message_queue_v5_downgrade_fails_closed_on_receipt_conflict(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "message-queue-receipt-downgrade-conflict.db"
    config = _message_queue_config(db_path)
    command_id = _prepare_v5_queue(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "ALTER TABLE runtime_user_message_idempotency "
            "RENAME TO runtime_user_message_idempotency_v5"
        )
        conn.execute(delivery_attempt_migration._LEGACY_RECEIPT_SCHEMA)
        conn.execute(
            """
            INSERT INTO runtime_user_message_idempotency (
                correlation_id, payload_fingerprint, first_command_id,
                delivery_status, created_at
            ) VALUES (
                'user_message:message-downgrade',
                'conflicting-fingerprint', ?, 'open', 10
            )
            """,
            (command_id,),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="downgrade could not preserve row"):
        command.downgrade(config, "v4")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT payload_fingerprint
            FROM runtime_user_message_idempotency_v5
            WHERE correlation_id = 'user_message:message-downgrade'
            """
        ).fetchone() == ("fingerprint-downgrade",)
        assert conn.execute(
            """
            SELECT payload_fingerprint
            FROM runtime_user_message_idempotency
            WHERE correlation_id = 'user_message:message-downgrade'
            """
        ).fetchone() == ("conflicting-fingerprint",)
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v5",)


def test_message_queue_v5_downgrade_fails_closed_on_command_conflict(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "message-queue-command-downgrade-conflict.db"
    config = _message_queue_config(db_path)
    command_id = _prepare_v5_queue(db_path)

    with sqlite3.connect(db_path) as conn:
        delivery_attempt_migration._downgrade_receipts(conn)
        for index_name in (
            "idx_runtime_commands_status_created",
            "idx_runtime_commands_type_status_created",
            "idx_runtime_commands_user_message_generation",
        ):
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
        conn.execute(
            "ALTER TABLE runtime_commands RENAME TO runtime_commands_v5"
        )
        conn.execute(delivery_attempt_migration._LEGACY_COMMAND_SCHEMA)
        conn.execute(
            """
            INSERT INTO runtime_commands (
                command_id, command_type, payload_json, correlation_id,
                status, retry_count, user_message_generation,
                created_at, updated_at
            ) VALUES (
                ?, 'user_message', '{"message":"conflicting target"}',
                'user_message:message-downgrade', 'claimed', 2, 4, 10, 11
            )
            """,
            (command_id,),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="could not preserve row"):
        command.downgrade(config, "v4")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT payload_json
            FROM runtime_commands_v5
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone() == ('{"message":"preserve me"}',)
        assert conn.execute(
            """
            SELECT payload_json
            FROM runtime_commands
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone() == ('{"message":"conflicting target"}',)
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v5",)
