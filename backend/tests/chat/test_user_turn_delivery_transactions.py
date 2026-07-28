"""Failure-boundary tests for durable user-turn delivery transactions."""

from __future__ import annotations

import sqlite3

import pytest

from magi.chat import ChatMessageRecord, ChatStore


def _runtime_envelope(*, turn_id: str, message: str) -> dict[str, object]:
    return {
        "source": "test",
        "user_id": "user-1",
        "session_id": "session-1",
        "turn_id": turn_id,
        "message": message,
        "attachments": [],
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_acceptance_rolls_back_every_chat_row_when_delivery_insert_fails(
    runtime_paths_with_schema,
) -> None:
    db_path = runtime_paths_with_schema.chat_db_path
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            CREATE TRIGGER abort_user_turn_delivery_insert
            BEFORE INSERT ON chat_user_turn_delivery
            BEGIN
                SELECT RAISE(ABORT, 'delivery insert blocked');
            END
            """)
        connection.commit()

    store = ChatStore(db_path=str(db_path))
    with pytest.raises(sqlite3.IntegrityError, match="delivery insert blocked"):
        await store.create_user_turn_once(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-acceptance-rollback",
            message_text="must roll back",
            created_at_ms=100,
            runtime_envelope=_runtime_envelope(
                turn_id="turn-acceptance-rollback",
                message="must roll back",
            ),
            request_fingerprint="fingerprint-rollback",
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE session_id = 'session-1'"
        ).fetchone() == (0,)
        assert connection.execute("""
            SELECT COUNT(*) FROM chat_turns
            WHERE turn_id = 'turn-acceptance-rollback'
            """).fetchone() == (0,)
        assert connection.execute("""
            SELECT COUNT(*) FROM chat_messages
            WHERE turn_id = 'turn-acceptance-rollback'
            """).fetchone() == (0,)
        assert connection.execute("""
            SELECT COUNT(*) FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-acceptance-rollback'
            """).fetchone() == (0,)


@pytest.mark.asyncio
async def test_terminal_reconciliation_rolls_back_turn_when_ledger_close_fails(
    runtime_paths_with_schema,
) -> None:
    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.create_user_turn_once(
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-reconcile-rollback",
        message_text="finish me",
        created_at_ms=100,
        runtime_envelope=_runtime_envelope(
            turn_id="turn-reconcile-rollback",
            message="finish me",
        ),
        request_fingerprint="fingerprint-reconcile",
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="assistant-reconcile-rollback",
            session_id="session-1",
            turn_id="turn-reconcile-rollback",
            user_id="user-1",
            role="assistant",
            message_kind="assistant_final",
            content_text="finished",
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=150,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            CREATE TRIGGER abort_delivery_terminal_reconcile
            BEFORE UPDATE OF delivery_state ON chat_user_turn_delivery
            WHEN OLD.turn_id = 'turn-reconcile-rollback'
             AND NEW.delivery_state = 'terminal'
            BEGIN
                SELECT RAISE(ABORT, 'ledger close blocked');
            END
            """)
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="ledger close blocked"):
        await store.reconcile_user_turn_terminal_surface(
            turn_id="turn-reconcile-rollback",
            expected_attempt_no=0,
            updated_at_ms=200,
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT status, completed_at_ms
            FROM chat_turns
            WHERE turn_id = 'turn-reconcile-rollback'
            """).fetchone() == ("queued", None)
        assert connection.execute("""
            SELECT delivery_state
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-reconcile-rollback'
            """).fetchone() == ("ready",)


@pytest.mark.asyncio
async def test_quarantine_rolls_back_visible_failure_when_ledger_close_fails(
    runtime_paths_with_schema,
) -> None:
    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.create_user_turn_once(
        session_id="session-1",
        user_id="user-1",
        turn_id="turn-quarantine-rollback",
        message_text="recover me",
        created_at_ms=100,
        runtime_envelope=_runtime_envelope(
            turn_id="turn-quarantine-rollback",
            message="recover me",
        ),
        request_fingerprint="fingerprint-quarantine",
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            CREATE TRIGGER abort_delivery_terminal_quarantine
            BEFORE UPDATE OF delivery_state ON chat_user_turn_delivery
            WHEN OLD.turn_id = 'turn-quarantine-rollback'
             AND NEW.delivery_state = 'terminal'
            BEGIN
                SELECT RAISE(ABORT, 'quarantine close blocked');
            END
            """)
        connection.commit()

    with pytest.raises(
        sqlite3.IntegrityError,
        match="quarantine close blocked",
    ):
        await store.quarantine_invalid_user_turn_delivery(
            turn_id="turn-quarantine-rollback",
            expected_attempt_no=0,
            user_message="Please retry",
            updated_at_ms=200,
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT status, completed_at_ms, error_text
            FROM chat_turns
            WHERE turn_id = 'turn-quarantine-rollback'
            """).fetchone() == ("queued", None, None)
        assert connection.execute("""
            SELECT delivery_state
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-quarantine-rollback'
            """).fetchone() == ("ready",)
        assert connection.execute("""
            SELECT COUNT(*)
            FROM chat_messages
            WHERE turn_id = 'turn-quarantine-rollback'
              AND role = 'assistant'
            """).fetchone() == (0,)
        assert connection.execute("""
            SELECT history_version
            FROM chat_sessions
            WHERE session_id = 'session-1'
            """).fetchone() == (1,)
