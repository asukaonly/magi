"""Track explicit user-message delivery attempts and current commands.

Revision ID: v5
Revises: v4
"""

from __future__ import annotations

import re

from alembic import op

revision = "v5"
down_revision = "v4"
branch_labels = None
depends_on = None

_CURRENT_RECEIPT_TABLE = "runtime_user_message_idempotency"
_LEGACY_RECEIPT_TABLE = "runtime_user_message_idempotency_v4"
_DOWNGRADE_RECEIPT_SOURCE_TABLE = "runtime_user_message_idempotency_v5"
_CURRENT_COMMAND_TABLE = "runtime_commands"
_DOWNGRADE_COMMAND_SOURCE_TABLE = "runtime_commands_v5"
_CURRENT_RECEIPT_COLUMNS = {
    "correlation_id",
    "payload_fingerprint",
    "current_attempt_no",
    "current_command_id",
    "delivery_status",
    "created_at",
}
_CURRENT_COMMAND_COLUMNS = {
    "command_id",
    "command_type",
    "payload_json",
    "correlation_id",
    "status",
    "retry_count",
    "claimed_by",
    "claimed_at",
    "last_error",
    "delivery_attempt_no",
    "created_at",
    "updated_at",
    "user_message_generation",
}
_LEGACY_COMMAND_COLUMNS = _CURRENT_COMMAND_COLUMNS - {"delivery_attempt_no"}
_LEGACY_RECEIPT_COLUMNS = {
    "correlation_id",
    "payload_fingerprint",
    "first_command_id",
    "delivery_status",
    "created_at",
}

_CURRENT_RECEIPT_SCHEMA = """
CREATE TABLE runtime_user_message_idempotency (
    correlation_id TEXT PRIMARY KEY,
    payload_fingerprint TEXT NOT NULL,
    current_attempt_no INTEGER NOT NULL
        CHECK (current_attempt_no >= 0),
    current_command_id INTEGER NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL
)
"""
_LEGACY_RECEIPT_SCHEMA = """
CREATE TABLE runtime_user_message_idempotency (
    correlation_id TEXT PRIMARY KEY,
    payload_fingerprint TEXT NOT NULL,
    first_command_id INTEGER NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL
)
"""
_LEGACY_COMMAND_SCHEMA = """
CREATE TABLE runtime_commands (
    command_id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    claimed_by TEXT,
    claimed_at REAL,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    user_message_generation INTEGER NOT NULL DEFAULT 0
)
"""
_COMMAND_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_runtime_commands_status_created
    ON runtime_commands(status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_runtime_commands_type_status_created
    ON runtime_commands(command_type, status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_runtime_commands_user_message_generation
    ON runtime_commands(command_type, user_message_generation);
"""


def _table_exists(connection, table: str) -> bool:
    return (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table,),
        ).fetchone()
        is not None
    )


def _column_rows(connection, table: str) -> dict[str, tuple[object, ...]]:
    return {
        str(row[1]): tuple(row)
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _table_sql(connection, table: str) -> str:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()
    return str(row[0] or "") if row is not None else ""


def _normalized_default(row: tuple[object, ...] | None) -> str | None:
    if row is None or row[4] is None:
        return None
    return str(row[4]).strip("() '\"")


def _validate_command_attempt_schema(connection, table: str) -> None:
    attempt = _column_rows(connection, table).get("delivery_attempt_no")
    has_check = re.search(
        r"check\s*\(\s*delivery_attempt_no\s*>=\s*0\s*\)",
        _table_sql(connection, table),
        flags=re.IGNORECASE,
    )
    if (
        attempt is None
        or str(attempt[2] or "").upper() != "INTEGER"
        or int(attempt[3] or 0) != 1
        or _normalized_default(attempt) != "0"
        or has_check is None
    ):
        raise RuntimeError(
            "Runtime command delivery-attempt column has an unsupported schema"
        )


def _validate_current_receipt_schema(connection, table: str) -> None:
    columns = _column_rows(connection, table)
    correlation = columns.get("correlation_id")
    fingerprint = columns.get("payload_fingerprint")
    attempt = columns.get("current_attempt_no")
    command = columns.get("current_command_id")
    status = columns.get("delivery_status")
    created = columns.get("created_at")
    has_check = re.search(
        r"check\s*\(\s*current_attempt_no\s*>=\s*0\s*\)",
        _table_sql(connection, table),
        flags=re.IGNORECASE,
    )
    if (
        correlation is None
        or str(correlation[2] or "").upper() != "TEXT"
        or int(correlation[5] or 0) != 1
        or fingerprint is None
        or str(fingerprint[2] or "").upper() != "TEXT"
        or int(fingerprint[3] or 0) != 1
        or attempt is None
        or str(attempt[2] or "").upper() != "INTEGER"
        or int(attempt[3] or 0) != 1
        or _normalized_default(attempt) is not None
        or command is None
        or str(command[2] or "").upper() != "INTEGER"
        or int(command[3] or 0) != 1
        or status is None
        or str(status[2] or "").upper() != "TEXT"
        or int(status[3] or 0) != 1
        or _normalized_default(status) != "open"
        or created is None
        or str(created[2] or "").upper() != "REAL"
        or int(created[3] or 0) != 1
        or has_check is None
    ):
        raise RuntimeError(
            "Runtime user-message receipt has an unsupported current schema"
        )


def _validate_legacy_receipt_schema(connection, table: str) -> None:
    columns = _column_rows(connection, table)
    correlation = columns.get("correlation_id")
    fingerprint = columns.get("payload_fingerprint")
    command = columns.get("first_command_id")
    status = columns.get("delivery_status")
    created = columns.get("created_at")
    if (
        correlation is None
        or str(correlation[2] or "").upper() != "TEXT"
        or int(correlation[5] or 0) != 1
        or fingerprint is None
        or str(fingerprint[2] or "").upper() != "TEXT"
        or int(fingerprint[3] or 0) != 1
        or command is None
        or str(command[2] or "").upper() != "INTEGER"
        or int(command[3] or 0) != 1
        or status is None
        or str(status[2] or "").upper() != "TEXT"
        or int(status[3] or 0) != 1
        or _normalized_default(status) != "open"
        or created is None
        or str(created[2] or "").upper() != "REAL"
        or int(created[3] or 0) != 1
    ):
        raise RuntimeError(
            "Runtime user-message receipt has an unsupported legacy schema"
        )


def _copy_legacy_receipts(connection) -> None:
    connection.execute(
        f"""
        INSERT OR IGNORE INTO {_CURRENT_RECEIPT_TABLE} (
            correlation_id,
            payload_fingerprint,
            current_attempt_no,
            current_command_id,
            delivery_status,
            created_at
        )
        SELECT correlation_id,
               payload_fingerprint,
               0,
               first_command_id,
               delivery_status,
               created_at
        FROM {_LEGACY_RECEIPT_TABLE}
        """
    )


def _assert_legacy_receipts_preserved(connection) -> None:
    mismatch = connection.execute(
        f"""
        SELECT legacy.correlation_id
        FROM {_LEGACY_RECEIPT_TABLE} AS legacy
        LEFT JOIN {_CURRENT_RECEIPT_TABLE} AS current
          ON current.correlation_id = legacy.correlation_id
        WHERE current.correlation_id IS NULL
           OR current.payload_fingerprint IS NOT legacy.payload_fingerprint
           OR current.current_attempt_no != 0
           OR current.current_command_id IS NOT legacy.first_command_id
           OR current.delivery_status IS NOT legacy.delivery_status
           OR current.created_at IS NOT legacy.created_at
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(
            "Runtime user-message receipt migration could not preserve "
            f"legacy row '{mismatch[0]}'"
        )


def _copy_current_receipts_to_legacy(connection) -> None:
    connection.execute(
        f"""
        INSERT OR IGNORE INTO {_CURRENT_RECEIPT_TABLE} (
            correlation_id,
            payload_fingerprint,
            first_command_id,
            delivery_status,
            created_at
        )
        SELECT correlation_id,
               payload_fingerprint,
               current_command_id,
               delivery_status,
               created_at
        FROM {_DOWNGRADE_RECEIPT_SOURCE_TABLE}
        """
    )


def _assert_current_receipts_downgraded(connection) -> None:
    mismatch = connection.execute(
        f"""
        SELECT source.correlation_id
        FROM {_DOWNGRADE_RECEIPT_SOURCE_TABLE} AS source
        LEFT JOIN {_CURRENT_RECEIPT_TABLE} AS legacy
          ON legacy.correlation_id = source.correlation_id
        WHERE legacy.correlation_id IS NULL
           OR legacy.payload_fingerprint IS NOT source.payload_fingerprint
           OR legacy.first_command_id IS NOT source.current_command_id
           OR legacy.delivery_status IS NOT source.delivery_status
           OR legacy.created_at IS NOT source.created_at
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(
            "Runtime user-message receipt downgrade could not preserve "
            f"row '{mismatch[0]}'"
        )


def _downgrade_receipts(connection) -> None:
    current_exists = _table_exists(connection, _CURRENT_RECEIPT_TABLE)
    source_exists = _table_exists(connection, _DOWNGRADE_RECEIPT_SOURCE_TABLE)
    if current_exists:
        columns = _columns(connection, _CURRENT_RECEIPT_TABLE)
        if columns == _CURRENT_RECEIPT_COLUMNS:
            if source_exists:
                raise RuntimeError(
                    "Ambiguous runtime user-message receipt downgrade state"
                )
            connection.execute(
                f"ALTER TABLE {_CURRENT_RECEIPT_TABLE} "
                f"RENAME TO {_DOWNGRADE_RECEIPT_SOURCE_TABLE}"
            )
            current_exists = False
            source_exists = True
        elif columns != _LEGACY_RECEIPT_COLUMNS:
            raise RuntimeError(
                "Unsupported runtime user-message receipt downgrade schema"
            )
    elif not source_exists:
        raise RuntimeError("Runtime user-message receipt downgrade source is missing")

    if source_exists:
        if (
            _columns(connection, _DOWNGRADE_RECEIPT_SOURCE_TABLE)
            != _CURRENT_RECEIPT_COLUMNS
        ):
            raise RuntimeError(
                "Unsupported runtime user-message receipt downgrade source schema"
            )
        _validate_current_receipt_schema(
            connection,
            _DOWNGRADE_RECEIPT_SOURCE_TABLE,
        )
        if not current_exists:
            connection.execute(_LEGACY_RECEIPT_SCHEMA)
        if (
            _columns(connection, _CURRENT_RECEIPT_TABLE)
            != _LEGACY_RECEIPT_COLUMNS
        ):
            raise RuntimeError(
                "Unsupported downgraded runtime user-message receipt schema"
            )
        _validate_legacy_receipt_schema(connection, _CURRENT_RECEIPT_TABLE)
        _copy_current_receipts_to_legacy(connection)
        _assert_current_receipts_downgraded(connection)
        connection.execute(f"DROP TABLE {_DOWNGRADE_RECEIPT_SOURCE_TABLE}")


def _copy_current_commands_to_legacy(connection) -> None:
    connection.execute(
        f"""
        INSERT OR IGNORE INTO {_CURRENT_COMMAND_TABLE} (
            command_id,
            command_type,
            payload_json,
            correlation_id,
            status,
            retry_count,
            claimed_by,
            claimed_at,
            last_error,
            created_at,
            updated_at,
            user_message_generation
        )
        SELECT command_id,
               command_type,
               payload_json,
               correlation_id,
               status,
               retry_count,
               claimed_by,
               claimed_at,
               last_error,
               created_at,
               updated_at,
               user_message_generation
        FROM {_DOWNGRADE_COMMAND_SOURCE_TABLE}
        """
    )


def _assert_current_commands_downgraded(connection) -> None:
    mismatch = connection.execute(
        f"""
        SELECT source.command_id
        FROM {_DOWNGRADE_COMMAND_SOURCE_TABLE} AS source
        LEFT JOIN {_CURRENT_COMMAND_TABLE} AS legacy
          ON legacy.command_id = source.command_id
        WHERE legacy.command_id IS NULL
           OR legacy.command_type IS NOT source.command_type
           OR legacy.payload_json IS NOT source.payload_json
           OR legacy.correlation_id IS NOT source.correlation_id
           OR legacy.status IS NOT source.status
           OR legacy.retry_count IS NOT source.retry_count
           OR legacy.claimed_by IS NOT source.claimed_by
           OR legacy.claimed_at IS NOT source.claimed_at
           OR legacy.last_error IS NOT source.last_error
           OR legacy.created_at IS NOT source.created_at
           OR legacy.updated_at IS NOT source.updated_at
           OR legacy.user_message_generation
                IS NOT source.user_message_generation
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(
            "Runtime command downgrade could not preserve "
            f"row '{mismatch[0]}'"
        )


def _downgrade_commands(connection) -> None:
    for index_name in (
        "idx_runtime_commands_status_created",
        "idx_runtime_commands_type_status_created",
        "idx_runtime_commands_user_message_generation",
    ):
        connection.execute(f"DROP INDEX IF EXISTS {index_name}")

    current_exists = _table_exists(connection, _CURRENT_COMMAND_TABLE)
    source_exists = _table_exists(connection, _DOWNGRADE_COMMAND_SOURCE_TABLE)
    if current_exists:
        columns = _columns(connection, _CURRENT_COMMAND_TABLE)
        if columns == _CURRENT_COMMAND_COLUMNS:
            if source_exists:
                raise RuntimeError("Ambiguous runtime command downgrade state")
            connection.execute(
                f"ALTER TABLE {_CURRENT_COMMAND_TABLE} "
                f"RENAME TO {_DOWNGRADE_COMMAND_SOURCE_TABLE}"
            )
            current_exists = False
            source_exists = True
        elif columns != _LEGACY_COMMAND_COLUMNS:
            raise RuntimeError("Unsupported runtime command downgrade schema")
    elif not source_exists:
        raise RuntimeError("Runtime command downgrade source is missing")

    if source_exists:
        if (
            _columns(connection, _DOWNGRADE_COMMAND_SOURCE_TABLE)
            != _CURRENT_COMMAND_COLUMNS
        ):
            raise RuntimeError(
                "Unsupported runtime command downgrade source schema"
            )
        _validate_command_attempt_schema(
            connection,
            _DOWNGRADE_COMMAND_SOURCE_TABLE,
        )
        if not current_exists:
            connection.execute(_LEGACY_COMMAND_SCHEMA)
        if _columns(connection, _CURRENT_COMMAND_TABLE) != _LEGACY_COMMAND_COLUMNS:
            raise RuntimeError("Unsupported downgraded runtime command schema")
        _copy_current_commands_to_legacy(connection)
        _assert_current_commands_downgraded(connection)
        connection.execute(f"DROP TABLE {_DOWNGRADE_COMMAND_SOURCE_TABLE}")

    connection.executescript(_COMMAND_INDEXES_SQL)


def upgrade() -> None:
    connection = op.get_bind().connection
    command_columns = _columns(connection, "runtime_commands")
    if not command_columns:
        raise RuntimeError("Runtime command table is missing")
    if "delivery_attempt_no" not in command_columns:
        connection.execute(
            """
            ALTER TABLE runtime_commands
            ADD COLUMN delivery_attempt_no INTEGER NOT NULL DEFAULT 0
                CHECK (delivery_attempt_no >= 0)
            """
        )
    if "delivery_attempt_no" not in _columns(connection, "runtime_commands"):
        raise RuntimeError("Runtime command delivery-attempt column is missing")
    _validate_command_attempt_schema(connection, _CURRENT_COMMAND_TABLE)

    current_exists = _table_exists(connection, _CURRENT_RECEIPT_TABLE)
    legacy_exists = _table_exists(connection, _LEGACY_RECEIPT_TABLE)
    if current_exists:
        receipt_columns = _columns(connection, _CURRENT_RECEIPT_TABLE)
        if receipt_columns == _LEGACY_RECEIPT_COLUMNS:
            if legacy_exists:
                raise RuntimeError(
                    "Ambiguous runtime user-message receipt migration state"
                )
            connection.execute(
                f"ALTER TABLE {_CURRENT_RECEIPT_TABLE} "
                f"RENAME TO {_LEGACY_RECEIPT_TABLE}"
            )
            current_exists = False
            legacy_exists = True
        elif receipt_columns != _CURRENT_RECEIPT_COLUMNS:
            raise RuntimeError("Unsupported runtime user-message receipt schema")
        else:
            _validate_current_receipt_schema(
                connection,
                _CURRENT_RECEIPT_TABLE,
            )
    elif not legacy_exists:
        raise RuntimeError("Runtime user-message receipt table is missing")

    if legacy_exists:
        if _columns(connection, _LEGACY_RECEIPT_TABLE) != _LEGACY_RECEIPT_COLUMNS:
            raise RuntimeError("Unsupported legacy runtime user-message receipt schema")
        _validate_legacy_receipt_schema(connection, _LEGACY_RECEIPT_TABLE)
        if not current_exists:
            connection.execute(_CURRENT_RECEIPT_SCHEMA)
            current_exists = True
        if (
            _columns(connection, _CURRENT_RECEIPT_TABLE)
            != _CURRENT_RECEIPT_COLUMNS
        ):
            raise RuntimeError("Unsupported current runtime user-message receipt schema")
        _validate_current_receipt_schema(
            connection,
            _CURRENT_RECEIPT_TABLE,
        )
        _copy_legacy_receipts(connection)
        _assert_legacy_receipts_preserved(connection)
        connection.execute(f"DROP TABLE {_LEGACY_RECEIPT_TABLE}")


def downgrade() -> None:
    connection = op.get_bind().connection
    _downgrade_receipts(connection)
    _downgrade_commands(connection)


def _columns(connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


__all__ = ["downgrade", "upgrade"]
