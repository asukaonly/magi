from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from magi.utils.runtime import RuntimePaths


def _list_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(row[0]) for row in cur.fetchall()}
    finally:
        conn.close()


def _read_journal_mode(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    finally:
        conn.close()


def _read_session_workspace_path(db_path: Path, session_id: str) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT workspace_path FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return row[0]
    finally:
        conn.close()


def _read_message_payload_json(db_path: Path, turn_id: str) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT payload_json FROM chat_messages WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        assert row is not None
        return json.loads(row[0] or "{}")
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_user_turn_rejects_case_variant_of_existing_session(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatStore
    from magi.chat.store import ChatTurnConflictError

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.create_user_turn_once(
        session_id="Session-Case",
        user_id="user-1",
        turn_id="turn-original-case",
        message_text="first",
        created_at_ms=100,
        runtime_envelope={
            "session_id": "Session-Case",
            "turn_id": "turn-original-case",
            "message": "first",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint="fingerprint-original-case",
    )

    with pytest.raises(ChatTurnConflictError, match="existing session identifier"):
        await store.create_user_turn_once(
            session_id="session-case",
            user_id="user-1",
            turn_id="turn-variant-case",
            message_text="second",
            created_at_ms=200,
            runtime_envelope={
                "session_id": "session-case",
                "turn_id": "turn-variant-case",
                "message": "second",
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint="fingerprint-variant-case",
        )

    with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM chat_sessions
            WHERE session_id = 'session-case' COLLATE NOCASE
            """
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_user_turn_delivery_ledger_tracks_exact_attempt_transitions(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    created = await store.create_user_turn_once(
        session_id="session-delivery",
        user_id="user-1",
        turn_id="turn-delivery",
        message_text="deliver once",
        created_at_ms=100,
        runtime_envelope={
            "session_id": "session-delivery",
            "turn_id": "turn-delivery",
            "message": "deliver once",
            "attachments": [],
            "metadata": {"source": "test"},
        },
        request_fingerprint="fingerprint-delivery",
    )

    assert created.created is True
    assert created.delivery_attempt_no == 0
    assert created.delivery_state == "ready"
    assert created.current_command_id is None
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-delivery",
        delivery_attempt_no=0,
        command_id=41,
        updated_at_ms=110,
    )
    assert not await store.mark_user_turn_delivery_queued(
        turn_id="turn-delivery",
        delivery_attempt_no=0,
        command_id=41,
        updated_at_ms=111,
    )
    assert not await store.mark_user_turn_delivery_admitted(
        turn_id="turn-delivery",
        delivery_attempt_no=0,
        command_id=42,
        updated_at_ms=120,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-delivery",
        delivery_attempt_no=0,
        command_id=41,
        updated_at_ms=121,
    )
    assert not await store.mark_user_turn_delivery_admitted(
        turn_id="turn-delivery",
        delivery_attempt_no=0,
        command_id=41,
        updated_at_ms=122,
    )
    assert await store.mark_user_turn_delivery_terminal(
        turn_id="turn-delivery",
        delivery_attempt_no=0,
        command_id=41,
        updated_at_ms=130,
    )
    assert not await store.mark_user_turn_delivery_terminal(
        turn_id="turn-delivery",
        delivery_attempt_no=0,
        command_id=41,
        updated_at_ms=131,
    )
    assert (
        await store.prepare_user_turn_delivery_attempt(
            turn_id="turn-delivery",
            expected_attempt_no=0,
            updated_at_ms=140,
        )
        is None
    )

    persisted = await store.get_user_turn_delivery(turn_id="turn-delivery")
    assert persisted is not None
    assert persisted.user_id == "user-1"
    assert persisted.session_id == "session-delivery"
    assert persisted.message_id == created.message.message_id
    assert persisted.delivery_attempt_no == 0
    assert persisted.delivery_state == "terminal"
    assert persisted.current_command_id == 41
    assert persisted.runtime_envelope["metadata"] == {"source": "test"}
    assert persisted.request_fingerprint == "fingerprint-delivery"


@pytest.mark.asyncio
async def test_admitted_delivery_recovery_invalidates_the_crashed_attempt(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.create_user_turn_once(
        session_id="session-crash",
        user_id="user-1",
        turn_id="turn-crash",
        message_text="resume after crash",
        created_at_ms=100,
        runtime_envelope={
            "session_id": "session-crash",
            "turn_id": "turn-crash",
            "message": "resume after crash",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint="fingerprint-crash",
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-crash",
        delivery_attempt_no=0,
        command_id=51,
        updated_at_ms=110,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-crash",
        delivery_attempt_no=0,
        command_id=51,
        updated_at_ms=120,
    )

    recovered = await store.prepare_user_turn_delivery_attempt(
        turn_id="turn-crash",
        expected_attempt_no=0,
        updated_at_ms=200,
    )

    assert recovered is not None
    assert recovered.delivery_attempt_no == 1
    assert recovered.delivery_state == "ready"
    assert recovered.current_command_id is None
    assert not await store.mark_user_turn_delivery_terminal(
        turn_id="turn-crash",
        delivery_attempt_no=0,
        command_id=51,
        updated_at_ms=210,
    )
    assert not await store.mark_user_turn_delivery_admitted(
        turn_id="turn-crash",
        delivery_attempt_no=0,
        command_id=51,
        updated_at_ms=211,
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-crash",
        delivery_attempt_no=1,
        command_id=52,
        updated_at_ms=220,
    )


@pytest.mark.asyncio
async def test_queue_consumer_can_admit_before_ingress_marks_queued(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.create_user_turn_once(
        session_id="session-fast-consumer",
        user_id="user-1",
        turn_id="turn-fast-consumer",
        message_text="consume immediately",
        created_at_ms=100,
        runtime_envelope={
            "session_id": "session-fast-consumer",
            "turn_id": "turn-fast-consumer",
            "message": "consume immediately",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint="fingerprint-fast-consumer",
    )

    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-fast-consumer",
        delivery_attempt_no=0,
        command_id=53,
        updated_at_ms=110,
    )
    assert not await store.mark_user_turn_delivery_queued(
        turn_id="turn-fast-consumer",
        delivery_attempt_no=0,
        command_id=53,
        updated_at_ms=120,
    )
    duplicate = await store.mark_user_turn_delivery_admitted(
        turn_id="turn-fast-consumer",
        delivery_attempt_no=0,
        command_id=53,
        updated_at_ms=121,
    )
    persisted = await store.get_user_turn_delivery(
        turn_id="turn-fast-consumer"
    )
    assert duplicate is False
    assert persisted is not None
    assert persisted.delivery_state == "admitted"
    assert persisted.current_command_id == 53


@pytest.mark.asyncio
async def test_recovery_can_close_each_nonterminal_state_when_final_already_exists(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatMessageRecord, ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    for turn_id in ("turn-ready-final", "turn-queued-final", "turn-admitted-final"):
        await store.create_user_turn_once(
            session_id="session-final-recovery",
            user_id="user-1",
            turn_id=turn_id,
            message_text=turn_id,
            created_at_ms=100,
            runtime_envelope={
                "session_id": "session-final-recovery",
                "turn_id": turn_id,
                "message": turn_id,
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint=f"fingerprint-{turn_id}",
        )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-queued-final",
        delivery_attempt_no=0,
        command_id=54,
        updated_at_ms=110,
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-admitted-final",
        delivery_attempt_no=0,
        command_id=55,
        updated_at_ms=111,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-admitted-final",
        delivery_attempt_no=0,
        command_id=55,
        updated_at_ms=112,
    )

    for index, turn_id in enumerate(
        ("turn-ready-final", "turn-queued-final", "turn-admitted-final"),
    ):
        await store.append_message(
            ChatMessageRecord(
                message_id=f"{turn_id}-assistant",
                session_id="session-final-recovery",
                turn_id=turn_id,
                user_id="user-1",
                role="assistant",
                message_kind="assistant_final",
                content_text="done",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=150 + index,
                sequence_no=100 + index,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )
        assert await store.reconcile_user_turn_terminal_surface(
            turn_id=turn_id,
            expected_attempt_no=0,
            updated_at_ms=200,
        )
        assert not await store.reconcile_user_turn_terminal_surface(
            turn_id=turn_id,
            expected_attempt_no=0,
            updated_at_ms=201,
        )
        persisted = await store.get_user_turn_delivery(turn_id=turn_id)
        assert persisted is not None
        assert persisted.delivery_state == "terminal"
        turn = await store.get_turn(turn_id)
        assert turn is not None
        assert turn.status == "completed"


@pytest.mark.asyncio
async def test_terminal_surface_reconciliation_never_recreates_deleted_turn(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatMessageRecord, ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.create_user_turn_once(
        session_id="session-deleted-recovery",
        user_id="user-1",
        turn_id="turn-deleted-recovery",
        message_text="remove me",
        created_at_ms=100,
        runtime_envelope={
            "session_id": "session-deleted-recovery",
            "turn_id": "turn-deleted-recovery",
            "message": "remove me",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint="fingerprint-deleted-recovery",
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="turn-deleted-recovery-assistant",
            session_id="session-deleted-recovery",
            turn_id="turn-deleted-recovery",
            user_id="user-1",
            role="assistant",
            message_kind="assistant_final",
            content_text="done",
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=150,
            sequence_no=100,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as connection:
        connection.execute(
            "DELETE FROM chat_user_turn_delivery WHERE turn_id = ?",
            ("turn-deleted-recovery",),
        )
        connection.execute(
            "DELETE FROM chat_messages WHERE turn_id = ?",
            ("turn-deleted-recovery",),
        )
        connection.execute(
            "DELETE FROM chat_turns WHERE turn_id = ?",
            ("turn-deleted-recovery",),
        )
        connection.commit()

    assert not await store.reconcile_user_turn_terminal_surface(
        turn_id="turn-deleted-recovery",
        expected_attempt_no=0,
        updated_at_ms=200,
    )
    assert await store.get_turn("turn-deleted-recovery") is None


@pytest.mark.asyncio
async def test_recovery_read_and_survivor_bump_are_stable_and_session_scoped(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatReadService, ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    for turn_id, created_at_ms in (
        ("turn-target", 100),
        ("turn-admitted", 110),
        ("turn-terminal", 120),
        ("turn-ready", 200),
    ):
        await store.create_user_turn_once(
            session_id="session-replay",
            user_id="user-1",
            turn_id=turn_id,
            message_text=turn_id,
            created_at_ms=created_at_ms,
            runtime_envelope={
                "session_id": "session-replay",
                "turn_id": turn_id,
                "message": turn_id,
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint=f"fingerprint-{turn_id}",
        )
    await store.create_user_turn_once(
        session_id="session-other",
        user_id="user-1",
        turn_id="turn-other",
        message_text="other",
        created_at_ms=50,
        runtime_envelope={
            "session_id": "session-other",
            "turn_id": "turn-other",
            "message": "other",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint="fingerprint-other",
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-target",
        delivery_attempt_no=0,
        command_id=61,
        updated_at_ms=300,
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-admitted",
        delivery_attempt_no=0,
        command_id=62,
        updated_at_ms=301,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-admitted",
        delivery_attempt_no=0,
        command_id=62,
        updated_at_ms=302,
    )
    assert await store.mark_user_turn_delivery_queued(
        turn_id="turn-terminal",
        delivery_attempt_no=0,
        command_id=63,
        updated_at_ms=303,
    )
    assert await store.mark_user_turn_delivery_admitted(
        turn_id="turn-terminal",
        delivery_attempt_no=0,
        command_id=63,
        updated_at_ms=304,
    )
    assert await store.mark_user_turn_delivery_terminal(
        turn_id="turn-terminal",
        delivery_attempt_no=0,
        command_id=63,
        updated_at_ms=305,
    )

    read_service = ChatReadService()
    read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    try:
        before = read_service.list_recoverable_user_turn_deliveries(
            "user-1",
            "session-replay",
        )
        assert [record.turn_id for record in before] == [
            "turn-target",
            "turn-admitted",
            "turn-ready",
        ]
        assert [record.sequence_no for record in before] == sorted(
            record.sequence_no for record in before
        )
        paged_turn_ids: list[str] = []
        after = None
        while True:
            page = read_service.list_recoverable_user_turn_deliveries(
                "user-1",
                "session-replay",
                limit=1,
                after=after,
            )
            if not page:
                break
            paged_turn_ids.append(page[0].turn_id)
            after = page[0]
        assert paged_turn_ids == [
            "turn-target",
            "turn-admitted",
            "turn-ready",
        ]

        survivors = read_service.bump_nonterminal_user_turn_delivery_attempts(
            "user-1",
            "session-replay",
            ["turn-target"],
            400,
        )

        assert [record.turn_id for record in survivors] == [
            "turn-admitted",
            "turn-ready",
        ]
        assert all(record.delivery_attempt_no == 1 for record in survivors)
        assert all(record.delivery_state == "ready" for record in survivors)
        assert all(record.current_command_id is None for record in survivors)
        after = read_service.list_recoverable_user_turn_deliveries(
            "user-1",
            "session-replay",
        )
        assert [record.turn_id for record in after] == [
            "turn-admitted",
            "turn-ready",
        ]
        assert (
            read_service.bump_nonterminal_user_turn_delivery_attempts(
                "user-1",
                "session-replay",
                ["turn-ready"],
                401,
                bump_survivors=False,
            )
            == []
        )
        final_recoverable = read_service.list_recoverable_user_turn_deliveries(
            "user-1",
            "session-replay",
        )
        assert [record.turn_id for record in final_recoverable] == [
            "turn-admitted"
        ]
    finally:
        read_service.close()

    target = await store.get_user_turn_delivery(turn_id="turn-target")
    ready_target = await store.get_user_turn_delivery(turn_id="turn-ready")
    admitted_survivor = await store.get_user_turn_delivery(
        turn_id="turn-admitted"
    )
    terminal = await store.get_user_turn_delivery(turn_id="turn-terminal")
    other = await store.get_user_turn_delivery(turn_id="turn-other")
    assert not await store.mark_user_turn_delivery_terminal(
        turn_id="turn-admitted",
        delivery_attempt_no=0,
        command_id=62,
        updated_at_ms=401,
    )
    assert target is not None and target.delivery_state == "terminal"
    assert ready_target is not None and ready_target.delivery_state == "terminal"
    assert admitted_survivor is not None
    assert admitted_survivor.delivery_attempt_no == 1
    assert admitted_survivor.delivery_state == "ready"
    assert terminal is not None and terminal.delivery_attempt_no == 0
    assert terminal.delivery_state == "terminal"
    assert other is not None and other.delivery_attempt_no == 0
    assert other.delivery_state == "ready"


@pytest.mark.asyncio
async def test_survivor_bump_reconciles_durable_terminal_turns_first(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatReadService, ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    for turn_id, disposition in (
        ("turn-completed-root", "root"),
        ("turn-completed-defer", "defer"),
        ("turn-merged", "augment"),
    ):
        await store.create_user_turn_once(
            session_id="session-terminal-reconcile",
            user_id="user-1",
            turn_id=turn_id,
            message_text=turn_id,
            created_at_ms=100,
            runtime_envelope={
                "source": "test",
                "user_id": "user-1",
                "session_id": "session-terminal-reconcile",
                "turn_id": turn_id,
                "message": turn_id,
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint=f"fingerprint-{turn_id}",
        )
        assert await store.mark_user_turn_delivery_queued(
            turn_id=turn_id,
            delivery_attempt_no=0,
            command_id={
                "turn-completed-root": 71,
                "turn-completed-defer": 72,
                "turn-merged": 73,
            }[turn_id],
            updated_at_ms=150,
        )
    with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as conn:
        conn.execute(
            """
            UPDATE chat_turns
            SET status = 'completed',
                run_disposition = 'root',
                response_mode = 'none'
            WHERE turn_id = 'turn-completed-root'
            """
        )
        conn.execute(
            """
            UPDATE chat_turns
            SET status = 'completed', run_disposition = 'defer'
            WHERE turn_id = 'turn-completed-defer'
            """
        )
        conn.execute(
            """
            UPDATE chat_turns
            SET status = 'merged', run_disposition = 'augment'
            WHERE turn_id = 'turn-merged'
            """
        )
        conn.commit()

    read_service = ChatReadService()
    read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    try:
        survivors = read_service.bump_nonterminal_user_turn_delivery_attempts(
            "user-1",
            "session-terminal-reconcile",
            [],
            200,
        )
    finally:
        read_service.close()

    assert [record.turn_id for record in survivors] == [
        "turn-completed-defer"
    ]
    assert survivors[0].delivery_attempt_no == 1
    assert survivors[0].delivery_state == "ready"
    completed_root = await store.get_user_turn_delivery(
        turn_id="turn-completed-root"
    )
    merged = await store.get_user_turn_delivery(turn_id="turn-merged")
    assert completed_root is not None
    assert completed_root.delivery_state == "terminal"
    assert merged is not None
    assert merged.delivery_state == "terminal"


@pytest.mark.asyncio
async def test_survivor_bump_scopes_reconciliation_and_requires_complete_visible_output(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatMessageRecord, ChatReadService, ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))

    async def create_delivery(*, session_id: str, turn_id: str) -> None:
        await store.create_user_turn_once(
            session_id=session_id,
            user_id="user-1",
            turn_id=turn_id,
            message_text=turn_id,
            created_at_ms=100,
            runtime_envelope={
                "source": "test",
                "user_id": "user-1",
                "session_id": session_id,
                "turn_id": turn_id,
                "message": turn_id,
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint=f"fingerprint-{turn_id}",
        )

    for turn_id in ("turn-full-rhythm", "turn-partial-rhythm", "turn-hidden-final"):
        await create_delivery(
            session_id="session-output-reconcile",
            turn_id=turn_id,
        )
    await create_delivery(
        session_id="session-output-other",
        turn_id="turn-other-session",
    )
    for index in range(2):
        await store.append_message(
            ChatMessageRecord(
                message_id=f"full-rhythm-{index}",
                session_id="session-output-reconcile",
                turn_id="turn-full-rhythm",
                user_id="user-1",
                role="assistant",
                message_kind="assistant_rhythm_segment",
                content_text=f"segment {index}",
                payload_json=(
                    '{"rhythm":{"segment_count":2,"segment_index":'
                    f"{index}}}}}"
                ),
                is_final=True,
                is_visible=True,
                created_at_ms=150 + index,
                sequence_no=100 + index,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )
    await store.append_message(
        ChatMessageRecord(
            message_id="partial-rhythm-0",
            session_id="session-output-reconcile",
            turn_id="turn-partial-rhythm",
            user_id="user-1",
            role="assistant",
            message_kind="assistant_rhythm_segment",
            content_text="partial",
            payload_json='{"rhythm":{"segment_count":2,"segment_index":0}}',
            is_final=True,
            is_visible=True,
            created_at_ms=160,
            sequence_no=110,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    await store.append_message(
        ChatMessageRecord(
            message_id="hidden-final-output",
            session_id="session-output-reconcile",
            turn_id="turn-hidden-final",
            user_id="user-1",
            role="assistant",
            message_kind="assistant_final",
            content_text="hidden",
            payload_json="{}",
            is_final=True,
            is_visible=False,
            created_at_ms=170,
            sequence_no=120,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    other_turn = await store.get_turn("turn-other-session")
    assert other_turn is not None
    other_turn.status = "completed"
    other_turn.response_mode = "none"
    other_turn.updated_at_ms = 180
    other_turn.completed_at_ms = 180
    await store.upsert_turn(other_turn)

    read_service = ChatReadService()
    read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    try:
        survivors = read_service.bump_nonterminal_user_turn_delivery_attempts(
            "user-1",
            "session-output-reconcile",
            [],
            200,
        )
    finally:
        read_service.close()

    assert {record.turn_id for record in survivors} == {
        "turn-partial-rhythm",
        "turn-hidden-final",
    }
    assert all(record.delivery_attempt_no == 1 for record in survivors)
    full = await store.get_user_turn_delivery(turn_id="turn-full-rhythm")
    partial = await store.get_user_turn_delivery(turn_id="turn-partial-rhythm")
    hidden = await store.get_user_turn_delivery(turn_id="turn-hidden-final")
    other = await store.get_user_turn_delivery(turn_id="turn-other-session")
    assert full is not None and full.delivery_state == "terminal"
    full_turn = await store.get_turn("turn-full-rhythm")
    assert full_turn is not None
    assert full_turn.status == "completed"
    assert full_turn.completed_at_ms == 151
    assert partial is not None and partial.delivery_state == "ready"
    assert hidden is not None and hidden.delivery_state == "ready"
    assert other is not None
    assert other.delivery_state == "ready"
    assert other.delivery_attempt_no == 0


def test_runtime_paths_exposes_chat_db_path(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)

    assert runtime_paths.chat_db_path == tmp_path / "data" / "chat" / "chat.db"


@pytest.mark.asyncio
async def test_chat_store_creates_chat_tables(runtime_paths_with_schema) -> None:
    from magi.chat import ChatStore

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))

    await store.initialize()

    try:
        tables = _list_tables(db_path)
        assert "chat_sessions" in tables
        assert "chat_turns" in tables
        assert "chat_messages" in tables
        assert "chat_message_asset_refs" in tables
        assert "chat_context_summaries" in tables
        journal_mode = _read_journal_mode(db_path)
        assert journal_mode == "wal"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_persists_turn_and_message_records(runtime_paths_with_schema) -> None:
    from magi.chat import ChatMessageRecord, ChatSessionRecord, ChatStore, ChatTurnRecord

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.upsert_session(
            ChatSessionRecord(
                session_id="session-1",
                user_id="user-1",
                title="",
                title_overridden=False,
                summary="",
                created_at_ms=100,
                updated_at_ms=100,
                last_message_at_ms=None,
                last_user_message_at_ms=None,
                last_message_preview="",
                last_user_message_preview="",
                message_count=0,
                workspace_path="/tmp/magi",
                archived_at_ms=None,
                deleted_at_ms=None,
            )
        )
        await store.upsert_turn(
            ChatTurnRecord(
                turn_id="turn-1",
                session_id="session-1",
                user_id="user-1",
                trace_id=None,
                status="queued",
                response_mode="final_only",
                execution_mode=None,
                ux_plan_json="{}",
                created_at_ms=100,
                updated_at_ms=100,
                completed_at_ms=None,
                error_text=None,
            )
        )
        await store.append_message(
            ChatMessageRecord(
                message_id="msg-user-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                role="user",
                message_kind="user_text",
                content_text="hello",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=100,
                sequence_no=1,
                replaces_message_id=None,
                replaced_by_message_id=None,
                persona_id="persona-a",
            )
        )
        await store.append_message(
            ChatMessageRecord(
                message_id="msg-assistant-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                role="assistant",
                message_kind="assistant_final",
                content_text="hi there",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=200,
                sequence_no=2,
                replaces_message_id=None,
                replaced_by_message_id=None,
                persona_id="persona-a",
            )
        )

        turn = await store.get_turn("turn-1")
        messages = await store.list_messages(session_id="session-1")
        tail = await store.list_messages(
            session_id="session-1",
            start_message_id="msg-assistant-1",
        )
        missing_frontier = await store.list_messages(
            session_id="session-1",
            start_message_id="missing-message",
        )

        assert turn is not None
        assert turn.status == "queued"
        assert [message.message_kind for message in messages] == ["user_text", "assistant_final"]
        assert [message.content_text for message in messages] == ["hello", "hi there"]
        assert [message.persona_id for message in messages] == ["persona-a", "persona-a"]
        assert [message.message_id for message in tail] == ["msg-assistant-1"]
        assert [message.message_id for message in missing_frontier] == [
            "msg-user-1",
            "msg-assistant-1",
        ]
        assert _read_session_workspace_path(db_path, "session-1") == "/tmp/magi"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_activates_latest_context_summary(runtime_paths_with_schema) -> None:
    from magi.chat import ChatContextSummaryRecord, ChatStore

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.create_user_turn(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            message_text="start",
            created_at_ms=100,
        )
        await store.activate_context_summary(
            ChatContextSummaryRecord(
                summary_id="summary-a",
                session_id="session-1",
                parent_summary_id=None,
                status="building",
                summary_kind="token_budget",
                persona_scope=None,
                covered_from_message_id="msg-1",
                covered_to_message_id="msg-10",
                first_kept_message_id="msg-11",
                covered_to_sequence_no=10,
                session_origin="Started with context design.",
                summary_text="Summary A",
                prompt_profile="general_chat",
                model_provider="test",
                model_id="model-a",
                token_count_before=1000,
                token_count_after=200,
                quality_status="ok",
                created_at_ms=200,
                updated_at_ms=200,
            )
        )
        await store.activate_context_summary(
            ChatContextSummaryRecord(
                summary_id="summary-b",
                session_id="session-1",
                parent_summary_id="summary-a",
                status="building",
                summary_kind="token_budget",
                persona_scope=None,
                covered_from_message_id="msg-1",
                covered_to_message_id="msg-20",
                first_kept_message_id="msg-21",
                covered_to_sequence_no=20,
                session_origin="Started with context design.",
                summary_text="Summary B",
                prompt_profile="general_chat",
                model_provider="test",
                model_id="model-a",
                token_count_before=1500,
                token_count_after=250,
                quality_status="ok",
                created_at_ms=300,
                updated_at_ms=300,
            )
        )

        active = await store.get_active_context_summary(
            session_id="session-1",
            summary_kind="token_budget",
        )

        assert active is not None
        assert active.summary_id == "summary-b"
        assert active.parent_summary_id == "summary-a"
        assert active.summary_text == "Summary B"
        assert active.first_kept_message_id == "msg-21"
        assert await store.get_history_version("session-1") == 3
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_activates_summary_only_for_expected_history_version(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatContextSummaryRecord, ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    try:
        await store.create_user_turn(
            session_id="session-conditional",
            user_id="user-1",
            turn_id="turn-1",
            message_text="start",
            created_at_ms=100,
        )
        record = ChatContextSummaryRecord(
            summary_id="summary-conditional",
            session_id="session-conditional",
            parent_summary_id=None,
            status="building",
            summary_kind="token_budget",
            persona_scope=None,
            covered_from_message_id="msg-1",
            covered_to_message_id="msg-1",
            first_kept_message_id="msg-2",
            covered_to_sequence_no=1,
            session_origin="origin",
            summary_text="summary",
            prompt_profile="general_chat",
            model_provider="test",
            model_id="model-a",
            token_count_before=1_000,
            token_count_after=100,
            quality_status="ok",
            created_at_ms=200,
            updated_at_ms=200,
        )

        rejected = await store.activate_context_summary_if_history_version(
            record,
            expected_history_version=0,
        )
        activated = await store.activate_context_summary_if_history_version(
            record,
            expected_history_version=1,
        )

        assert rejected is False
        assert activated is True
        assert await store.get_history_version("session-conditional") == 2
        active = await store.get_active_context_summary(
            session_id="session-conditional",
            summary_kind="token_budget",
        )
        assert active is not None
        assert active.summary_id == "summary-conditional"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_bumps_history_version_when_creating_user_turn(runtime_paths_with_schema) -> None:
    from magi.chat import ChatStore

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.create_user_turn(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            message_text="hello",
            created_at_ms=100,
        )

        history_version = await store.get_history_version("session-1")

        assert history_version == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_history_survives_reinitialization(runtime_paths_with_schema) -> None:
    from magi.chat import ChatMessageRecord, ChatStore

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        user_message = await store.create_user_turn(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            message_text="What did I say about sushi?",
            created_at_ms=100,
            persona_id="persona-history",
        )
        await store.append_message(
            ChatMessageRecord(
                message_id="msg-assistant-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                role="assistant",
                message_kind="assistant_final",
                content_text="You said sushi is your favorite.",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=200,
                sequence_no=2,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )
    finally:
        await store.shutdown()

    reloaded = ChatStore(db_path=str(db_path))
    await reloaded.initialize()
    try:
        messages = await reloaded.list_messages(session_id="session-1")
        assert [message.message_id for message in messages] == [user_message.message_id, "msg-assistant-1"]
        assert [message.content_text for message in messages] == [
            "What did I say about sushi?",
            "You said sushi is your favorite.",
        ]
        assert messages[0].persona_id == "persona-history"
        assert await reloaded.get_history_version("session-1") == 1
    finally:
        await reloaded.shutdown()


@pytest.mark.asyncio
async def test_chat_store_persists_attachment_metadata_on_user_turn(runtime_paths_with_schema) -> None:
    from magi.chat import ChatStore
    from magi.core.chat_assets.mutations import run_chat_asset_mutation
    from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService

    db_path = runtime_paths_with_schema.chat_db_path
    attachment = await run_chat_asset_mutation(
        LocalChatAttachmentIngestionService(
            runtime_paths=runtime_paths_with_schema,
        ).ingest_attachment,
        session_id="session-1",
        turn_id="turn-attachments",
        original_name="photo.png",
        content=b"png",
        mime_type="image/png",
    )
    store = ChatStore(
        db_path=str(db_path),
        runtime_paths=runtime_paths_with_schema,
    )
    await store.initialize()

    try:
        await store.create_user_turn(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-attachments",
            message_text="",
            attachment_payloads=[attachment],
            created_at_ms=100,
        )

        payload_json = _read_message_payload_json(db_path, "turn-attachments")

        assert payload_json["attachments"] == [
            {
                "attachment_id": attachment["attachment_id"],
                "kind": "image",
                    "original_name": "photo.png",
                    "mime_type": "image/png",
                    "size_bytes": 3,
                    "parse_status": "not_applicable",
                }
            ]
        assert "storage_path" not in payload_json["attachments"][0]
        assert "sha256" not in payload_json["attachments"][0]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_indexes_original_and_derived_message_assets(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.chat import ChatStore
    from magi.chat.storage import serialization

    runtime_paths = runtime_paths_with_schema
    monkeypatch.setattr(serialization, "get_runtime_paths", lambda: runtime_paths)
    source_path = (
        runtime_paths.chat_files_dir
        / "session-assets"
        / "turn-assets"
        / "attachment-assets__attachment.txt"
    )
    derived_path = (
        runtime_paths.chat_derived_dir
        / "session-assets"
        / "turn-assets"
        / "attachment-assets.txt"
    )
    source_path.parent.mkdir(parents=True, exist_ok=True)
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("source", encoding="utf-8")
    derived_path.write_text("derived", encoding="utf-8")

    store = ChatStore(db_path=str(runtime_paths.chat_db_path))
    await store.create_user_turn(
        session_id="session-assets",
        user_id="user-1",
        turn_id="turn-assets",
        message_text="attached",
        attachment_payloads=[
            {
                "attachment_id": "attachment-assets",
                "kind": "file",
                "storage_path": source_path.relative_to(runtime_paths.base_dir).as_posix(),
                "derived_text_path": str(derived_path),
            }
        ],
        created_at_ms=100,
    )

    with sqlite3.connect(runtime_paths.chat_db_path) as conn:
        rows = conn.execute(
            """
            SELECT asset_key, storage_rel_path, asset_kind
            FROM chat_message_asset_refs
            ORDER BY asset_key
            """
        ).fetchall()
        attachment_storage_path = conn.execute(
            """
            SELECT storage_rel_path
            FROM chat_attachments
            WHERE attachment_id = 'attachment-assets'
            """
        ).fetchone()
    assert rows == [
        (
            "derived/session-assets/turn-assets/attachment-assets.txt",
            "data/resources/chat/derived/session-assets/turn-assets/"
            "attachment-assets.txt",
            "derived_text",
        ),
        (
            "files/session-assets/turn-assets/attachment-assets__attachment.txt",
            "data/resources/chat/files/session-assets/turn-assets/"
            "attachment-assets__attachment.txt",
            "attachment",
        ),
    ]
    assert attachment_storage_path == (
        "data/resources/chat/files/session-assets/turn-assets/"
        "attachment-assets__attachment.txt",
    )
    await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_rejects_a_retargeted_derived_file_without_partial_rows(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.chat import ChatStore
    from magi.chat.asset_validation import ChatAssetOwnershipError
    from magi.chat.storage import serialization

    runtime_paths = runtime_paths_with_schema
    monkeypatch.setattr(serialization, "get_runtime_paths", lambda: runtime_paths)
    source_path = (
        runtime_paths.chat_files_dir
        / "session-assets"
        / "turn-assets"
        / "attachment-assets__attachment.txt"
    )
    derived_path = (
        runtime_paths.chat_derived_dir
        / "session-assets"
        / "turn-assets"
        / "attachment-assets.txt"
    )
    target_path = (
        runtime_paths.chat_derived_dir
        / "other-session"
        / "other-turn"
        / "other-attachment.txt"
    )
    source_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("source", encoding="utf-8")
    target_path.write_text("other derived text", encoding="utf-8")
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        derived_path.symlink_to(target_path)
    except OSError:
        pytest.skip("Symlinks are not available on this platform")

    store = ChatStore(
        db_path=str(runtime_paths.chat_db_path),
        runtime_paths=runtime_paths,
    )
    with pytest.raises(ChatAssetOwnershipError):
        await store.create_user_turn(
            session_id="session-assets",
            user_id="user-1",
            turn_id="turn-assets",
            message_text="attached",
            attachment_payloads=[
                {
                    "attachment_id": "attachment-assets",
                    "kind": "file",
                    "storage_path": str(source_path),
                    "derived_text_path": str(derived_path),
                }
            ],
            created_at_ms=100,
        )

    with sqlite3.connect(runtime_paths.chat_db_path) as conn:
        message_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_messages
            WHERE turn_id = 'turn-assets'
            """
        ).fetchone()[0]
        attachment_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_attachments
            WHERE turn_id = 'turn-assets'
            """
        ).fetchone()[0]
        reference_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_message_asset_refs
            """
        ).fetchone()[0]

    assert message_count == 0
    assert attachment_count == 0
    assert reference_count == 0
    assert target_path.read_text(encoding="utf-8") == "other derived text"
    await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_marks_interim_messages_replaced_by_final(runtime_paths_with_schema) -> None:
    from magi.chat import ChatMessageRecord, ChatSessionRecord, ChatStore, ChatTurnRecord

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.upsert_session(
            ChatSessionRecord(
                session_id="session-1",
                user_id="user-1",
                title="",
                title_overridden=False,
                summary="",
                created_at_ms=100,
                updated_at_ms=100,
                last_message_at_ms=None,
                last_user_message_at_ms=None,
                last_message_preview="",
                last_user_message_preview="",
                message_count=0,
                archived_at_ms=None,
                deleted_at_ms=None,
            )
        )
        await store.upsert_turn(
            ChatTurnRecord(
                turn_id="turn-2",
                session_id="session-1",
                user_id="user-1",
                trace_id=None,
                status="running",
                response_mode="interim_then_final",
                execution_mode="orchestration",
                ux_plan_json="{}",
                created_at_ms=100,
                updated_at_ms=100,
                completed_at_ms=None,
                error_text=None,
            )
        )
        await store.append_message(
            ChatMessageRecord(
                message_id="msg-interim",
                session_id="session-1",
                turn_id="turn-2",
                user_id="user-1",
                role="assistant",
                message_kind="assistant_interim",
                content_text="let me check",
                payload_json="{}",
                is_final=False,
                is_visible=True,
                created_at_ms=150,
                sequence_no=1,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )
        await store.append_message(
            ChatMessageRecord(
                message_id="msg-final",
                session_id="session-1",
                turn_id="turn-2",
                user_id="user-1",
                role="assistant",
                message_kind="assistant_final",
                content_text="done",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=200,
                sequence_no=2,
                replaces_message_id="msg-interim",
                replaced_by_message_id=None,
            )
        )
        await store.mark_message_replaced(message_id="msg-interim", replaced_by_message_id="msg-final")

        interim = await store.get_message("msg-interim")
        final = await store.get_message("msg-final")

        assert interim is not None
        assert final is not None
        assert interim.replaced_by_message_id == "msg-final"
        assert final.replaces_message_id == "msg-interim"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_delivery_cancel_requires_matching_session_and_user(
    runtime_paths_with_schema,
) -> None:
    from magi.chat import ChatStore

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    await store.create_user_turn(
        session_id="session-owned",
        user_id="user-owned",
        turn_id="turn-owned",
        message_text="Keep the owner boundary",
        created_at_ms=1710000000000,
    )

    try:
        assert not await store.cancel_user_turn_delivery_if_active(
            turn_id="turn-owned",
            expected_session_id="session-other",
            expected_user_id="user-owned",
            run_id=None,
            run_revision=0,
            reason="user_cancel",
            updated_at_ms=1710000000001,
        )
        assert not await store.cancel_user_turn_delivery_if_active(
            turn_id="turn-owned",
            expected_session_id="session-owned",
            expected_user_id="user-other",
            run_id=None,
            run_revision=0,
            reason="user_cancel",
            updated_at_ms=1710000000002,
        )

        turn = await store.get_turn("turn-owned")
        delivery = await store.get_user_turn_delivery(turn_id="turn-owned")
        assert turn is not None
        assert turn.status == "queued"
        assert delivery is not None
        assert delivery.delivery_state == "ready"
    finally:
        await store.shutdown()
