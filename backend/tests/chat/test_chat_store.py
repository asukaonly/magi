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
                orchestration_id=None,
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

        active = await store.get_active_context_summary(session_id="session-1")

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
            session_id="session-conditional"
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

    db_path = runtime_paths_with_schema.chat_db_path
    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.create_user_turn(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-attachments",
            message_text="",
            attachment_payloads=[{"kind": "image", "attachment_id": "att-1"}],
            created_at_ms=100,
        )

        payload_json = _read_message_payload_json(db_path, "turn-attachments")

        assert payload_json["attachments"] == [{"kind": "image", "attachment_id": "att-1"}]
    finally:
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
                orchestration_id=None,
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
async def test_replayed_turn_reuses_existing_final_message(runtime_paths_with_schema) -> None:
    from magi.chat import ChatSessionRecord, ChatStore, ChatTurnRecord
    from magi.chat.task_agent.postprocess.message_writes import ChatAssistantMessageWriter

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await store.initialize()
    turn = ChatTurnRecord(
        turn_id="turn-replayed",
        session_id="session-replayed",
        user_id="user-1",
        trace_id=None,
        orchestration_id=None,
        status="running",
        response_mode="final_only",
        execution_mode="direct_llm",
        ux_plan_json="{}",
        created_at_ms=100,
        updated_at_ms=100,
        completed_at_ms=None,
        error_text=None,
    )
    await store.upsert_session(
        ChatSessionRecord(
            session_id=turn.session_id,
            user_id=turn.user_id,
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
    await store.upsert_turn(turn)
    writer = ChatAssistantMessageWriter(chat_store=store)

    try:
        first = await writer.append_final_message(
            turn=turn,
            turn_id=turn.turn_id,
            response_text="first completed answer",
            attachments=None,
            message_payload=None,
            completed_at_ms=200,
            reply_to_message_id=None,
            persona_id=None,
        )
        replayed = await writer.append_final_message(
            turn=turn,
            turn_id=turn.turn_id,
            response_text="answer from replayed execution",
            attachments=None,
            message_payload=None,
            completed_at_ms=300,
            reply_to_message_id=None,
            persona_id=None,
        )

        assert first is not None
        assert replayed is not None
        assert replayed.message_id == first.message_id
        assert replayed.content_text == "first completed answer"
        final_messages = [
            message
            for message in await store.list_messages(session_id=turn.session_id)
            if message.turn_id == turn.turn_id and message.message_kind == "assistant_final"
        ]
        assert len(final_messages) == 1
    finally:
        await store.shutdown()
