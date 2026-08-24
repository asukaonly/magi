"""Replace ambiguous enqueue progress with an attempt-scoped delivery ledger."""

from __future__ import annotations

import json
import re
from typing import Any

from alembic import op

revision = "v4"
down_revision = "v3"
branch_labels = None
depends_on = None

_FINAL_COLUMNS = {
    "turn_id",
    "projection_completed",
    "delivery_attempt_no",
    "delivery_state",
    "current_command_id",
    "runtime_envelope_json",
    "request_fingerprint",
    "created_at_ms",
    "updated_at_ms",
}
_LEGACY_COLUMNS = {
    "turn_id",
    "projection_completed",
    "runtime_enqueued",
    "runtime_envelope_json",
    "request_fingerprint",
    "created_at_ms",
    "updated_at_ms",
}
_LEGACY_TABLE = "chat_user_turn_delivery_v3"
_CURRENT_TABLE = "chat_user_turn_delivery"
_DOWNGRADE_SOURCE_TABLE = "chat_user_turn_delivery_v4"

_CREATE_LEDGER_SQL = """
CREATE TABLE chat_user_turn_delivery (
    turn_id TEXT PRIMARY KEY,
    projection_completed INTEGER NOT NULL DEFAULT 0,
    delivery_attempt_no INTEGER NOT NULL DEFAULT 0
        CHECK (delivery_attempt_no >= 0),
    delivery_state TEXT NOT NULL DEFAULT 'ready'
        CHECK (delivery_state IN ('ready', 'queued', 'admitted', 'terminal')),
    current_command_id INTEGER,
    runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
    request_fingerprint TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    CHECK (
        (delivery_state = 'ready' AND current_command_id IS NULL)
        OR delivery_state = 'terminal'
        OR current_command_id IS NOT NULL
    )
)
"""
_CREATE_LEGACY_LEDGER_SQL = """
CREATE TABLE chat_user_turn_delivery (
    turn_id TEXT PRIMARY KEY,
    projection_completed INTEGER NOT NULL DEFAULT 0,
    runtime_enqueued INTEGER NOT NULL DEFAULT 0,
    runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
    request_fingerprint TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
)
"""
_MAX_RHYTHM_SEGMENT_COUNT = 64
_LEGACY_DELIVERY_STATE_EXPRESSION = """
CASE
    WHEN TRIM(COALESCE(legacy.runtime_envelope_json, '')) IN ('', '{}')
        OR EXISTS (
            SELECT 1
            FROM chat_turns AS turns
            WHERE turns.turn_id = legacy.turn_id
              AND (
                  turns.status IN ('cancelled', 'merged', 'interrupted')
                  OR (
                      turns.status = 'completed'
                      AND LOWER(
                          TRIM(COALESCE(turns.run_disposition, ''))
                      ) != 'message'
                      AND LOWER(
                          TRIM(COALESCE(turns.response_mode, ''))
                      ) IN ('none', 'reaction_only')
                  )
              )
        )
        OR EXISTS (
            SELECT 1
            FROM chat_messages AS assistant_messages
            WHERE assistant_messages.turn_id = legacy.turn_id
              AND assistant_messages.role = 'assistant'
              AND assistant_messages.message_kind = 'assistant_final'
              AND assistant_messages.is_final = 1
              AND assistant_messages.is_visible = 1
        )
    THEN 'terminal'
    ELSE 'ready'
END
"""


def _table_exists(connection: Any, table: str) -> bool:
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


def _columns(connection: Any, table: str = _CURRENT_TABLE) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def _table_sql(connection: Any, table: str) -> str:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()
    return str(row[0] or "") if row is not None else ""


def _validate_final_ledger_schema(connection: Any, table: str) -> None:
    column_rows = {
        str(row[1]): tuple(row)
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    attempt = column_rows.get("delivery_attempt_no")
    state = column_rows.get("delivery_state")
    command = column_rows.get("current_command_id")
    table_sql = _table_sql(connection, table)
    attempt_check = re.search(
        r"check\s*\(\s*delivery_attempt_no\s*>=\s*0\s*\)",
        table_sql,
        flags=re.IGNORECASE,
    )
    state_check = re.search(
        r"delivery_state\s+in\s*\(\s*'ready'\s*,\s*'queued'\s*,\s*"
        r"'admitted'\s*,\s*'terminal'\s*\)",
        table_sql,
        flags=re.IGNORECASE,
    )
    command_check = re.search(
        r"\(\s*delivery_state\s*=\s*'ready'\s+and\s+"
        r"current_command_id\s+is\s+null\s*\)\s*or\s*"
        r"delivery_state\s*=\s*'terminal'\s*or\s*"
        r"current_command_id\s+is\s+not\s+null",
        table_sql,
        flags=re.IGNORECASE,
    )
    if (
        attempt is None
        or str(attempt[2] or "").upper() != "INTEGER"
        or int(attempt[3] or 0) != 1
        or str(attempt[4] or "").strip("() '\"") != "0"
        or state is None
        or str(state[2] or "").upper() != "TEXT"
        or int(state[3] or 0) != 1
        or str(state[4] or "").strip("() '\"") != "ready"
        or command is None
        or int(command[3] or 0) != 0
        or attempt_check is None
        or state_check is None
        or command_check is None
    ):
        raise RuntimeError(
            "Chat user-turn delivery table has an unsupported final schema"
        )


def _validate_recovery_index(connection: Any) -> None:
    index_name = "idx_chat_user_turn_delivery_recovery"
    index_rows = {
        str(row[1]): tuple(row)
        for row in connection.execute(
            f"PRAGMA index_list({_CURRENT_TABLE})"
        ).fetchall()
    }
    index_row = index_rows.get(index_name)
    columns = tuple(
        str(row[2])
        for row in connection.execute(f"PRAGMA index_info({index_name})")
    )
    if (
        index_row is None
        or int(index_row[2] or 0) != 0
        or int(index_row[4] or 0) != 0
        or columns != ("delivery_state", "updated_at_ms", "turn_id")
    ):
        raise RuntimeError(
            "Chat user-turn delivery recovery index has an unsupported schema"
        )


def _strict_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = int(normalized)
    except ValueError:
        return None
    if normalized not in {str(parsed), f"+{parsed}"}:
        return None
    return parsed


def _complete_rhythm_payloads(payload_jsons: list[str]) -> bool:
    expected_count: int | None = None
    indexes: set[int] = set()
    for payload_json in payload_jsons:
        try:
            rhythm = json.loads(payload_json or "{}")["rhythm"]
            segment_count = _strict_int(rhythm["segment_count"])
            segment_index = _strict_int(rhythm["segment_index"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
        if segment_count is None or segment_index is None:
            return False
        if not 1 <= segment_count <= _MAX_RHYTHM_SEGMENT_COUNT:
            return False
        if expected_count is None:
            expected_count = segment_count
        elif expected_count != segment_count:
            return False
        if not 0 <= segment_index < segment_count or segment_index in indexes:
            return False
        indexes.add(segment_index)
    return (
        expected_count is not None
        and len(payload_jsons) == expected_count
        and indexes == set(range(expected_count))
    )


def _mark_complete_rhythm_deliveries(connection: Any) -> None:
    rows = connection.execute(
        """
        SELECT messages.turn_id, messages.payload_json
        FROM chat_messages AS messages
        JOIN chat_user_turn_delivery AS delivery
          ON delivery.turn_id = messages.turn_id
        WHERE delivery.delivery_state = 'ready'
          AND messages.role = 'assistant'
          AND messages.message_kind = 'assistant_rhythm_segment'
          AND messages.is_final = 1
          AND messages.is_visible = 1
        ORDER BY messages.turn_id, messages.sequence_no, messages.message_id
        """
    ).fetchall()
    payloads_by_turn: dict[str, list[str]] = {}
    for turn_id, payload_json in rows:
        payloads_by_turn.setdefault(str(turn_id), []).append(
            str(payload_json or "{}")
        )
    completed_turn_ids = [
        turn_id
        for turn_id, payloads in payloads_by_turn.items()
        if _complete_rhythm_payloads(payloads)
    ]
    if completed_turn_ids:
        connection.executemany(
            """
            UPDATE chat_user_turn_delivery
            SET delivery_state = 'terminal'
            WHERE turn_id = ?
            """,
            ((turn_id,) for turn_id in completed_turn_ids),
        )
        for turn_id in completed_turn_ids:
            latest_output = connection.execute(
                """
                SELECT MAX(created_at_ms)
                FROM chat_messages
                WHERE turn_id = ?
                  AND role = 'assistant'
                  AND message_kind = 'assistant_rhythm_segment'
                  AND is_final = 1
                  AND is_visible = 1
                """,
                (turn_id,),
            ).fetchone()
            turn_row = connection.execute(
                """
                SELECT updated_at_ms
                FROM chat_turns
                WHERE turn_id = ?
                  AND status IN ('queued', 'running')
                """,
                (turn_id,),
            ).fetchone()
            if latest_output is None or turn_row is None:
                continue
            completed_at_ms = max(
                int(latest_output[0] or 0),
                int(turn_row[0] or 0),
            )
            connection.execute(
                """
                UPDATE chat_turns
                SET status = 'completed',
                    updated_at_ms = ?,
                    completed_at_ms = ?
                WHERE turn_id = ?
                  AND status IN ('queued', 'running')
                """,
                (completed_at_ms, completed_at_ms, turn_id),
            )


def _complete_visible_final_turns(connection: Any) -> None:
    """Keep migrated turn state aligned with terminal visible final replies."""

    rows = connection.execute(
        """
        SELECT turns.turn_id,
               turns.updated_at_ms,
               MAX(messages.created_at_ms)
        FROM chat_turns AS turns
        JOIN chat_user_turn_delivery AS delivery
          ON delivery.turn_id = turns.turn_id
         AND delivery.delivery_state = 'terminal'
        JOIN chat_messages AS messages
          ON messages.turn_id = turns.turn_id
         AND messages.role = 'assistant'
         AND messages.message_kind = 'assistant_final'
         AND messages.is_final = 1
         AND messages.is_visible = 1
        WHERE turns.status IN ('queued', 'running')
        GROUP BY turns.turn_id, turns.updated_at_ms
        """
    ).fetchall()
    for turn_id, updated_at_ms, latest_output_ms in rows:
        completed_at_ms = max(
            int(updated_at_ms or 0),
            int(latest_output_ms or 0),
        )
        connection.execute(
            """
            UPDATE chat_turns
            SET status = 'completed',
                updated_at_ms = ?,
                completed_at_ms = ?
            WHERE turn_id = ?
              AND status IN ('queued', 'running')
            """,
            (completed_at_ms, completed_at_ms, str(turn_id)),
        )


def _copy_legacy_deliveries(connection: Any) -> None:
    connection.execute(
        f"""
        INSERT OR IGNORE INTO {_CURRENT_TABLE} (
            turn_id,
            projection_completed,
            delivery_attempt_no,
            delivery_state,
            current_command_id,
            runtime_envelope_json,
            request_fingerprint,
            created_at_ms,
            updated_at_ms
        )
        SELECT legacy.turn_id,
               legacy.projection_completed,
               0,
               {_LEGACY_DELIVERY_STATE_EXPRESSION},
               NULL,
               legacy.runtime_envelope_json,
               legacy.request_fingerprint,
               legacy.created_at_ms,
               legacy.updated_at_ms
        FROM {_LEGACY_TABLE} AS legacy
        """
    )


def _assert_legacy_deliveries_preserved(connection: Any) -> None:
    mismatch = connection.execute(
        f"""
        SELECT legacy.turn_id
        FROM {_LEGACY_TABLE} AS legacy
        LEFT JOIN {_CURRENT_TABLE} AS current
          ON current.turn_id = legacy.turn_id
        WHERE current.turn_id IS NULL
           OR current.projection_completed IS NOT legacy.projection_completed
           OR current.delivery_attempt_no != 0
           OR current.delivery_state IS NOT (
               {_LEGACY_DELIVERY_STATE_EXPRESSION}
           )
           OR current.current_command_id IS NOT NULL
           OR current.runtime_envelope_json IS NOT legacy.runtime_envelope_json
           OR current.request_fingerprint IS NOT legacy.request_fingerprint
           OR current.created_at_ms IS NOT legacy.created_at_ms
           OR current.updated_at_ms IS NOT legacy.updated_at_ms
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(
            "Chat user-turn delivery migration could not preserve "
            f"legacy row '{mismatch[0]}'"
        )


def _copy_current_deliveries_to_legacy(connection: Any) -> None:
    connection.execute(
        f"""
        INSERT OR IGNORE INTO {_CURRENT_TABLE} (
            turn_id,
            projection_completed,
            runtime_enqueued,
            runtime_envelope_json,
            request_fingerprint,
            created_at_ms,
            updated_at_ms
        )
        SELECT turn_id,
               projection_completed,
               CASE WHEN delivery_state = 'terminal' THEN 1 ELSE 0 END,
               runtime_envelope_json,
               request_fingerprint,
               created_at_ms,
               updated_at_ms
        FROM {_DOWNGRADE_SOURCE_TABLE}
        """
    )


def _assert_current_deliveries_downgraded(connection: Any) -> None:
    mismatch = connection.execute(
        f"""
        SELECT source.turn_id
        FROM {_DOWNGRADE_SOURCE_TABLE} AS source
        LEFT JOIN {_CURRENT_TABLE} AS legacy
          ON legacy.turn_id = source.turn_id
        WHERE legacy.turn_id IS NULL
           OR legacy.projection_completed IS NOT source.projection_completed
           OR legacy.runtime_enqueued !=
                CASE WHEN source.delivery_state = 'terminal' THEN 1 ELSE 0 END
           OR legacy.runtime_envelope_json IS NOT source.runtime_envelope_json
           OR legacy.request_fingerprint IS NOT source.request_fingerprint
           OR legacy.created_at_ms IS NOT source.created_at_ms
           OR legacy.updated_at_ms IS NOT source.updated_at_ms
        LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise RuntimeError(
            "Chat user-turn delivery downgrade could not preserve "
            f"row '{mismatch[0]}'"
        )


def upgrade() -> None:
    connection = op.get_bind().connection
    current_exists = _table_exists(connection, _CURRENT_TABLE)
    legacy_exists = _table_exists(connection, _LEGACY_TABLE)

    if current_exists:
        current_columns = _columns(connection)
        if current_columns == _LEGACY_COLUMNS:
            if legacy_exists:
                raise RuntimeError(
                    "Ambiguous chat user-turn delivery migration state"
                )
            connection.execute(
                f"ALTER TABLE {_CURRENT_TABLE} RENAME TO {_LEGACY_TABLE}"
            )
            current_exists = False
            legacy_exists = True
        elif current_columns != _FINAL_COLUMNS:
            raise RuntimeError("Unsupported chat user-turn delivery schema")
        else:
            _validate_final_ledger_schema(connection, _CURRENT_TABLE)
    elif not legacy_exists:
        raise RuntimeError("Chat user-turn delivery table is missing")

    if legacy_exists:
        if _columns(connection, _LEGACY_TABLE) != _LEGACY_COLUMNS:
            raise RuntimeError("Unsupported legacy chat user-turn delivery schema")
        if not current_exists:
            connection.execute(_CREATE_LEDGER_SQL)
            current_exists = True
        if _columns(connection) != _FINAL_COLUMNS:
            raise RuntimeError("Unsupported current chat user-turn delivery schema")
        _validate_final_ledger_schema(connection, _CURRENT_TABLE)
        _copy_legacy_deliveries(connection)
        _assert_legacy_deliveries_preserved(connection)
        connection.execute(f"DROP TABLE {_LEGACY_TABLE}")

    _mark_complete_rhythm_deliveries(connection)
    _complete_visible_final_turns(connection)
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_user_turn_delivery_recovery
        ON chat_user_turn_delivery(delivery_state, updated_at_ms, turn_id)
        """
    )
    _validate_recovery_index(connection)


def downgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("DROP INDEX IF EXISTS idx_chat_user_turn_delivery_recovery")
    current_exists = _table_exists(connection, _CURRENT_TABLE)
    source_exists = _table_exists(connection, _DOWNGRADE_SOURCE_TABLE)

    if current_exists:
        current_columns = _columns(connection)
        if current_columns == _FINAL_COLUMNS:
            if source_exists:
                raise RuntimeError(
                    "Ambiguous chat user-turn delivery downgrade state"
                )
            connection.execute(
                f"ALTER TABLE {_CURRENT_TABLE} "
                f"RENAME TO {_DOWNGRADE_SOURCE_TABLE}"
            )
            current_exists = False
            source_exists = True
        elif current_columns != _LEGACY_COLUMNS:
            raise RuntimeError("Unsupported chat user-turn delivery downgrade schema")
    elif not source_exists:
        raise RuntimeError("Chat user-turn delivery downgrade source is missing")

    if source_exists:
        if _columns(connection, _DOWNGRADE_SOURCE_TABLE) != _FINAL_COLUMNS:
            raise RuntimeError(
                "Unsupported chat user-turn delivery downgrade source schema"
            )
        _validate_final_ledger_schema(connection, _DOWNGRADE_SOURCE_TABLE)
        if not current_exists:
            connection.execute(_CREATE_LEGACY_LEDGER_SQL)
        if _columns(connection) != _LEGACY_COLUMNS:
            raise RuntimeError(
                "Unsupported downgraded chat user-turn delivery schema"
            )
        _copy_current_deliveries_to_legacy(connection)
        _assert_current_deliveries_downgraded(connection)
        connection.execute(f"DROP TABLE {_DOWNGRADE_SOURCE_TABLE}")
