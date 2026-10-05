"""Migration coverage for durable assistant-memory projection work."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def _insert_outbox_row(
    connection: sqlite3.Connection,
    *,
    message_id: str,
    state: str = "pending",
    attempt_count: int = 0,
    lease_token: str | None = None,
    lease_expires_at_ms: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO chat_assistant_memory_outbox (
            canonical_message_id, user_id, session_id, turn_id,
            content_text, created_at_ms, state, attempt_count,
            next_attempt_at_ms, lease_token, lease_expires_at_ms,
            last_error, updated_at_ms
        ) VALUES (?, 'user-1', 'session-1', 'turn-1', 'answer', 100,
                  ?, ?, 0, ?, ?, NULL, 101)
        """,
        (
            message_id,
            state,
            attempt_count,
            lease_token,
            lease_expires_at_ms,
        ),
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_fresh_and_upgraded_outboxes_preserve_chat_and_enforce_leases(
    tmp_path: Path,
    legacy: bool,
) -> None:
    db_path = tmp_path / "chat-v4.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v4" if legacy else "v1")

    with sqlite3.connect(db_path) as connection:
        if legacy:
            connection.execute("DROP INDEX IF EXISTS idx_chat_assistant_memory_outbox_session")
            connection.execute("DROP INDEX IF EXISTS idx_chat_assistant_memory_outbox_ready")
            connection.execute("DROP TABLE IF EXISTS chat_assistant_memory_outbox")
        connection.execute("""
            INSERT INTO chat_sessions (
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', 'Existing chat', 1, 2)
            """)
        connection.execute("""
            INSERT INTO chat_turns (
                turn_id, session_id, user_id, status, response_mode,
                created_at_ms, updated_at_ms
            ) VALUES (
                'turn-1', 'session-1', 'user-1', 'completed',
                'final_only', 1, 2
            )
            """)
        connection.execute("""
            INSERT INTO chat_messages (
                message_id, session_id, turn_id, user_id, role,
                message_kind, content_text, created_at_ms, sequence_no
            ) VALUES (
                'message-existing', 'session-1', 'turn-1', 'user-1',
                'assistant', 'assistant_final', 'existing answer', 2, 1
            )
            """)
        connection.commit()
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v4" if legacy else "v1",
        )

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            CHAT_MIGRATION_HEAD,
        )
        assert connection.execute(
            "SELECT title FROM chat_sessions WHERE session_id = 'session-1'"
        ).fetchone() == ("Existing chat",)
        assert connection.execute(
            "SELECT content_text FROM chat_messages WHERE message_id = 'message-existing'"
        ).fetchone() == ("existing answer",)
        assert (
            {row[0] for row in connection.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                  AND name LIKE 'idx_chat_assistant_memory_outbox_%'
                """)}
            == {
                "idx_chat_assistant_memory_outbox_ready",
                "idx_chat_assistant_memory_outbox_session",
            }
        )

        _insert_outbox_row(connection, message_id="message-pending")
        _insert_outbox_row(
            connection,
            message_id="message-claimed",
            state="claimed",
            attempt_count=1,
            lease_token="lease-1",
            lease_expires_at_ms=500,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_outbox_row(
                connection,
                message_id="invalid-pending-lease",
                lease_token="unexpected",
                lease_expires_at_ms=500,
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_outbox_row(
                connection,
                message_id="invalid-claimed-no-lease",
                state="claimed",
                attempt_count=1,
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_outbox_row(
                connection,
                message_id="invalid-negative-attempt",
                attempt_count=-1,
            )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute("""
            SELECT canonical_message_id, state, attempt_count,
                   lease_token, lease_expires_at_ms
            FROM chat_assistant_memory_outbox
            ORDER BY canonical_message_id
            """).fetchall()
            == [
                ("message-claimed", "claimed", 1, "lease-1", 500),
                ("message-pending", "pending", 0, None, None),
            ]
        )
