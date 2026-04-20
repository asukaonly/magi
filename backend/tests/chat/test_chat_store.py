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
async def test_chat_store_creates_chat_tables(tmp_path: Path) -> None:
    from magi.chat import ChatStore

    db_path = tmp_path / "chat.db"
    store = ChatStore(db_path=str(db_path))

    await store.initialize()

    try:
        tables = _list_tables(db_path)
        assert "chat_sessions" in tables
        assert "chat_turns" in tables
        assert "chat_messages" in tables
        journal_mode = _read_journal_mode(db_path)
        assert journal_mode == "wal"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_migrates_workspace_path_column(tmp_path: Path) -> None:
    from magi.chat import ChatStore

    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE chat_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                title_overridden INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                last_message_at_ms INTEGER,
                last_user_message_at_ms INTEGER,
                last_message_preview TEXT NOT NULL DEFAULT '',
                last_user_message_preview TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                history_version INTEGER NOT NULL DEFAULT 0,
                archived_at_ms INTEGER,
                deleted_at_ms INTEGER
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    store = ChatStore(db_path=str(db_path))
    await store.initialize()

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()
            }
        finally:
            conn.close()

        assert "workspace_path" in columns
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_persists_turn_and_message_records(tmp_path: Path) -> None:
    from magi.chat import ChatMessageRecord, ChatSessionRecord, ChatStore, ChatTurnRecord

    db_path = tmp_path / "chat.db"
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
                workspace_path="/Users/asuka/code/magi",
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
            )
        )

        turn = await store.get_turn("turn-1")
        messages = await store.list_messages(session_id="session-1")

        assert turn is not None
        assert turn.status == "queued"
        assert [message.message_kind for message in messages] == ["user_text", "assistant_final"]
        assert [message.content_text for message in messages] == ["hello", "hi there"]
        assert _read_session_workspace_path(db_path, "session-1") == "/Users/asuka/code/magi"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_chat_store_bumps_history_version_when_creating_user_turn(tmp_path: Path) -> None:
    from magi.chat import ChatStore

    db_path = tmp_path / "chat.db"
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
async def test_chat_store_persists_attachment_metadata_on_user_turn(tmp_path: Path) -> None:
    from magi.chat import ChatStore

    db_path = tmp_path / "chat.db"
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
async def test_chat_store_marks_interim_messages_replaced_by_final(tmp_path: Path) -> None:
    from magi.chat import ChatMessageRecord, ChatSessionRecord, ChatStore, ChatTurnRecord

    db_path = tmp_path / "chat.db"
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
