"""Migration coverage for the attempt-scoped chat delivery ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.migrations.chat.versions import (
    v4_user_turn_delivery_ledger as delivery_ledger_migration,
)


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def _prepare_legacy_delivery(db_path: Path) -> None:
    config = _chat_config(db_path)
    command.upgrade(config, "v3")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_chat_user_turn_delivery_recovery")
        conn.execute("DROP TABLE chat_user_turn_delivery")
        conn.execute(delivery_ledger_migration._CREATE_LEGACY_LEDGER_SQL)
        conn.execute(
            """
            INSERT INTO chat_user_turn_delivery (
                turn_id, projection_completed, runtime_enqueued,
                runtime_envelope_json, request_fingerprint,
                created_at_ms, updated_at_ms
            ) VALUES (
                'turn-resume', 1, 1,
                '{"message":"preserve me","metadata":{"source":"test"}}',
                'fingerprint-resume', 100, 101
            )
            """
        )
        conn.commit()


def test_v4_rebuilds_legacy_delivery_rows_without_losing_envelopes(
    tmp_path: Path,
) -> None:
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    db_path = tmp_path / "chat-v3.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v3")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_chat_user_turn_delivery_recovery")
        conn.execute("DROP TABLE chat_user_turn_delivery")
        conn.execute(
            """
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
        )
        conn.executemany(
            """
            INSERT INTO chat_user_turn_delivery (
                turn_id, projection_completed, runtime_enqueued,
                runtime_envelope_json, request_fingerprint,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "turn-missing-envelope",
                    1,
                    0,
                    "{}",
                    "",
                    50,
                    51,
                ),
                (
                    "turn-ready",
                    1,
                    0,
                    '{"message":"ready","metadata":{"source":"test"}}',
                    "fingerprint-ready",
                    100,
                    101,
                ),
                (
                    "turn-terminal",
                    1,
                    1,
                    '{"message":"done","metadata":{"source":"test"}}',
                    "fingerprint-terminal",
                    200,
                    201,
                ),
                (
                    "turn-terminal-rhythm",
                    1,
                    1,
                    '{"message":"done in parts","metadata":{"source":"test"}}',
                    "fingerprint-terminal-rhythm",
                    210,
                    211,
                ),
                (
                    "turn-partial-rhythm",
                    1,
                    1,
                    '{"message":"unfinished parts","metadata":{"source":"test"}}',
                    "fingerprint-partial-rhythm",
                    220,
                    221,
                ),
                (
                    "turn-completed-defer",
                    1,
                    1,
                    '{"message":"later","metadata":{"source":"test"}}',
                    "fingerprint-defer",
                    300,
                    301,
                ),
                (
                    "turn-completed-missing-final",
                    1,
                    1,
                    '{"message":"unfinished","metadata":{"source":"test"}}',
                    "fingerprint-missing-final",
                    350,
                    351,
                ),
                (
                    "turn-failed",
                    1,
                    1,
                    '{"message":"retry","metadata":{"source":"test"}}',
                    "fingerprint-failed",
                    400,
                    401,
                ),
                (
                    "turn-merged",
                    1,
                    1,
                    '{"message":"merged","metadata":{"source":"test"}}',
                    "fingerprint-merged",
                    500,
                    501,
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO chat_turns (
                turn_id, session_id, user_id, status, response_mode,
                ux_plan_json, created_at_ms, updated_at_ms, run_disposition
            ) VALUES (?, 'session-1', 'user-1', ?, 'final_only', '{}', ?, ?, ?)
            """,
            [
                ("turn-terminal", "queued", 200, 201, "root"),
                (
                    "turn-terminal-rhythm",
                    "queued",
                    210,
                    211,
                    "root",
                ),
                ("turn-completed-defer", "completed", 300, 301, "defer"),
                (
                    "turn-completed-missing-final",
                    "completed",
                    350,
                    351,
                    "root",
                ),
                ("turn-failed", "failed", 400, 401, "root"),
                ("turn-merged", "merged", 500, 501, "augment"),
            ],
        )
        conn.execute(
            """
            INSERT INTO chat_messages (
                message_id, session_id, turn_id, user_id, role,
                message_kind, content_text, payload_json, is_final,
                is_visible, created_at_ms, sequence_no
            ) VALUES (
                'msg-terminal', 'session-1', 'turn-terminal', 'user-1',
                'assistant', 'assistant_final', 'done', '{}', 1, 1, 202, 1
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO chat_messages (
                message_id, session_id, turn_id, user_id, role,
                message_kind, content_text, payload_json, is_final,
                is_visible, created_at_ms, sequence_no
            ) VALUES (?, 'session-1', ?, 'user-1', 'assistant',
                      'assistant_rhythm_segment', ?, ?, 1, 1, ?, ?)
            """,
            [
                (
                    "msg-rhythm-0",
                    "turn-terminal-rhythm",
                    "part 0",
                    '{"rhythm":{"segment_count":2,"segment_index":0}}',
                    212,
                    2,
                ),
                (
                    "msg-rhythm-1",
                    "turn-terminal-rhythm",
                    "part 1",
                    '{"rhythm":{"segment_count":2,"segment_index":1}}',
                    213,
                    3,
                ),
                (
                    "msg-partial-rhythm-0",
                    "turn-partial-rhythm",
                    "part 0",
                    '{"rhythm":{"segment_count":2,"segment_index":0}}',
                    222,
                    4,
                ),
            ],
        )
        conn.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(chat_user_turn_delivery)"
            ).fetchall()
        }
        assert "runtime_enqueued" not in columns
        assert {
            "delivery_attempt_no",
            "delivery_state",
            "current_command_id",
        } <= columns
        assert conn.execute(
            """
            SELECT turn_id, projection_completed, delivery_attempt_no,
                   delivery_state, current_command_id,
                   runtime_envelope_json, request_fingerprint,
                   created_at_ms, updated_at_ms
            FROM chat_user_turn_delivery
            ORDER BY turn_id
            """
        ).fetchall() == [
            (
                "turn-completed-defer",
                1,
                0,
                "ready",
                None,
                '{"message":"later","metadata":{"source":"test"}}',
                "fingerprint-defer",
                300,
                301,
            ),
            (
                "turn-completed-missing-final",
                1,
                0,
                "ready",
                None,
                '{"message":"unfinished","metadata":{"source":"test"}}',
                "fingerprint-missing-final",
                350,
                351,
            ),
            (
                "turn-failed",
                1,
                0,
                "ready",
                None,
                '{"message":"retry","metadata":{"source":"test"}}',
                "fingerprint-failed",
                400,
                401,
            ),
            (
                "turn-merged",
                1,
                0,
                "terminal",
                None,
                '{"message":"merged","metadata":{"source":"test"}}',
                "fingerprint-merged",
                500,
                501,
            ),
            (
                "turn-missing-envelope",
                1,
                0,
                "terminal",
                None,
                "{}",
                "",
                50,
                51,
            ),
            (
                "turn-partial-rhythm",
                1,
                0,
                "ready",
                None,
                '{"message":"unfinished parts","metadata":{"source":"test"}}',
                "fingerprint-partial-rhythm",
                220,
                221,
            ),
            (
                "turn-ready",
                1,
                0,
                "ready",
                None,
                '{"message":"ready","metadata":{"source":"test"}}',
                "fingerprint-ready",
                100,
                101,
            ),
            (
                "turn-terminal",
                1,
                0,
                "terminal",
                None,
                '{"message":"done","metadata":{"source":"test"}}',
                "fingerprint-terminal",
                200,
                201,
            ),
            (
                "turn-terminal-rhythm",
                1,
                0,
                "terminal",
                None,
                '{"message":"done in parts","metadata":{"source":"test"}}',
                "fingerprint-terminal-rhythm",
                210,
                211,
            ),
        ]
        assert conn.execute(
            """
            SELECT turn_id, status, completed_at_ms
            FROM chat_turns
            WHERE turn_id IN ('turn-terminal', 'turn-terminal-rhythm')
            ORDER BY turn_id
            """
        ).fetchall() == [
            ("turn-terminal", "completed", 202),
            ("turn-terminal-rhythm", "completed", 213),
        ]
        index_row = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_chat_user_turn_delivery_recovery'
            """
        ).fetchone()
        assert index_row is not None
        assert "delivery_state" in str(index_row[0])
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO chat_user_turn_delivery (
                    turn_id, projection_completed, delivery_attempt_no,
                    delivery_state, current_command_id,
                    runtime_envelope_json, request_fingerprint,
                    created_at_ms, updated_at_ms
                ) VALUES (
                    'turn-invalid', 0, 0, 'queued', NULL,
                    '{"message":"invalid"}', 'invalid', 300, 300
                )
                """
            )


@pytest.mark.parametrize(
    "interruption",
    ["rename_only", "create_before_copy", "copy_before_drop"],
)
def test_v4_upgrade_resumes_each_table_rebuild_boundary(
    tmp_path: Path,
    interruption: str,
) -> None:
    db_path = tmp_path / f"chat-{interruption}.db"
    config = _chat_config(db_path)
    _prepare_legacy_delivery(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "ALTER TABLE chat_user_turn_delivery "
            "RENAME TO chat_user_turn_delivery_v3"
        )
        if interruption != "rename_only":
            conn.execute(delivery_ledger_migration._CREATE_LEDGER_SQL)
        if interruption == "copy_before_drop":
            delivery_ledger_migration._copy_legacy_deliveries(conn)
        conn.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT turn_id, projection_completed, delivery_attempt_no,
                   delivery_state, current_command_id,
                   runtime_envelope_json, request_fingerprint,
                   created_at_ms, updated_at_ms
            FROM chat_user_turn_delivery
            """
        ).fetchone() == (
            "turn-resume",
            1,
            0,
            "ready",
            None,
            '{"message":"preserve me","metadata":{"source":"test"}}',
            "fingerprint-resume",
            100,
            101,
        )
        assert conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'chat_user_turn_delivery_v3'
            """
        ).fetchone() is None
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CHAT_MIGRATION_HEAD,)
        assert conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_chat_user_turn_delivery_recovery'
            """
        ).fetchone() == (1,)


def test_v4_upgrade_fails_closed_when_rebuild_rows_conflict(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-upgrade-conflict.db"
    config = _chat_config(db_path)
    _prepare_legacy_delivery(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "ALTER TABLE chat_user_turn_delivery "
            "RENAME TO chat_user_turn_delivery_v3"
        )
        conn.execute(delivery_ledger_migration._CREATE_LEDGER_SQL)
        conn.execute(
            """
            INSERT INTO chat_user_turn_delivery (
                turn_id, projection_completed, delivery_attempt_no,
                delivery_state, current_command_id,
                runtime_envelope_json, request_fingerprint,
                created_at_ms, updated_at_ms
            ) VALUES (
                'turn-resume', 1, 0, 'terminal', NULL,
                '{"message":"preserve me","metadata":{"source":"test"}}',
                'fingerprint-resume', 100, 101
            )
            """
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
                  AND name LIKE 'chat_user_turn_delivery%'
                """
            )
        }
        assert {
            "chat_user_turn_delivery",
            "chat_user_turn_delivery_v3",
        } <= tables
        assert conn.execute(
            """
            SELECT runtime_envelope_json, request_fingerprint
            FROM chat_user_turn_delivery_v3
            WHERE turn_id = 'turn-resume'
            """
        ).fetchone() == (
            '{"message":"preserve me","metadata":{"source":"test"}}',
            "fingerprint-resume",
        )
        assert conn.execute(
            """
            SELECT delivery_state, runtime_envelope_json, request_fingerprint
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-resume'
            """
        ).fetchone() == (
            "terminal",
            '{"message":"preserve me","metadata":{"source":"test"}}',
            "fingerprint-resume",
        )
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v3",)


def test_v4_upgrade_rejects_same_columns_without_required_constraints(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-invalid-final-schema.db"
    config = _chat_config(db_path)
    _prepare_legacy_delivery(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "ALTER TABLE chat_user_turn_delivery "
            "RENAME TO chat_user_turn_delivery_v3"
        )
        conn.execute(
            """
            CREATE TABLE chat_user_turn_delivery (
                turn_id TEXT PRIMARY KEY,
                projection_completed INTEGER NOT NULL DEFAULT 0,
                delivery_attempt_no INTEGER NOT NULL DEFAULT 0,
                delivery_state TEXT NOT NULL DEFAULT 'ready',
                current_command_id INTEGER,
                runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
                request_fingerprint TEXT NOT NULL DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            )
            """
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="unsupported final schema"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT request_fingerprint
            FROM chat_user_turn_delivery_v3
            WHERE turn_id = 'turn-resume'
            """
        ).fetchone() == ("fingerprint-resume",)
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v3",)


@pytest.mark.parametrize(
    "interruption",
    ["rename_only", "create_before_copy", "copy_before_drop"],
)
def test_v4_downgrade_resumes_each_table_rebuild_boundary(
    tmp_path: Path,
    interruption: str,
) -> None:
    db_path = tmp_path / f"chat-downgrade-{interruption}.db"
    config = _chat_config(db_path)
    _prepare_legacy_delivery(db_path)
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_chat_user_turn_delivery_recovery")
        conn.execute(
            "ALTER TABLE chat_user_turn_delivery "
            "RENAME TO chat_user_turn_delivery_v4"
        )
        if interruption != "rename_only":
            conn.execute(delivery_ledger_migration._CREATE_LEGACY_LEDGER_SQL)
        if interruption == "copy_before_drop":
            delivery_ledger_migration._copy_current_deliveries_to_legacy(conn)
        conn.commit()

    command.downgrade(config, "v3")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT turn_id, projection_completed, runtime_enqueued,
                   runtime_envelope_json, request_fingerprint,
                   created_at_ms, updated_at_ms
            FROM chat_user_turn_delivery
            """
        ).fetchone() == (
            "turn-resume",
            1,
            0,
            '{"message":"preserve me","metadata":{"source":"test"}}',
            "fingerprint-resume",
            100,
            101,
        )
        assert conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'chat_user_turn_delivery_v4'
            """
        ).fetchone() is None
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v3",)
        assert conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_chat_user_turn_delivery_recovery'
            """
        ).fetchone() is None

    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            """
            SELECT delivery_attempt_no, delivery_state, current_command_id
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-resume'
            """
        ).fetchone() == (0, "ready", None)


def test_v4_downgrade_fails_closed_when_rebuild_rows_conflict(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-downgrade-conflict.db"
    config = _chat_config(db_path)
    _prepare_legacy_delivery(db_path)
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_chat_user_turn_delivery_recovery")
        conn.execute(
            "ALTER TABLE chat_user_turn_delivery "
            "RENAME TO chat_user_turn_delivery_v4"
        )
        conn.execute(delivery_ledger_migration._CREATE_LEGACY_LEDGER_SQL)
        conn.execute(
            """
            INSERT INTO chat_user_turn_delivery (
                turn_id, projection_completed, runtime_enqueued,
                runtime_envelope_json, request_fingerprint,
                created_at_ms, updated_at_ms
            ) VALUES (
                'turn-resume', 1, 0,
                '{"message":"conflicting target"}',
                'conflicting-fingerprint', 100, 101
            )
            """
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="downgrade could not preserve row"):
        command.downgrade(config, "v3")

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name LIKE 'chat_user_turn_delivery%'
                """
            )
        }
        assert {
            "chat_user_turn_delivery",
            "chat_user_turn_delivery_v4",
        } <= tables
        assert conn.execute(
            """
            SELECT runtime_envelope_json, request_fingerprint
            FROM chat_user_turn_delivery_v4
            WHERE turn_id = 'turn-resume'
            """
        ).fetchone() == (
            '{"message":"preserve me","metadata":{"source":"test"}}',
            "fingerprint-resume",
        )
        assert conn.execute(
            """
            SELECT runtime_envelope_json, request_fingerprint
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-resume'
            """
        ).fetchone() == (
            '{"message":"conflicting target"}',
            "conflicting-fingerprint",
        )
        assert conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("v4",)
