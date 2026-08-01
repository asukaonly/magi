"""Crash and late-write coverage for global chat clearing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from _shared.db_schema import apply_chain_schema
from magi.chat.asset_gc import ChatAssetGC
from magi.chat.contracts import ChatMessageRecord, ChatSessionRecord
from magi.chat.read_service import ChatReadService
from magi.chat.store import ChatStore, ChatTurnConflictError
from magi.utils.runtime import RuntimePaths


def _build_read_service(tmp_path: Path) -> tuple[ChatReadService, RuntimePaths]:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    apply_chain_schema("chat", runtime_paths.chat_db_path)
    service = object.__new__(ChatReadService)
    service._runtime_paths = runtime_paths
    service._chat_db_path = runtime_paths.chat_db_path
    service._l1_db_path = runtime_paths.l1_memory_db_path
    service._runtime_trace_db_path = runtime_paths.runtime_trace_db_path
    service._asset_gc = ChatAssetGC(runtime_paths=runtime_paths)
    service._conn = None
    return service, runtime_paths


def _seed_session(service: ChatReadService, session_id: str) -> None:
    connection = service._get_conn()
    connection.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms
        ) VALUES (?, 'local_user', 'Old chat', 1, 1)
        """,
        (session_id,),
    )
    connection.commit()


@pytest.mark.asyncio
async def test_full_clear_rejects_retried_old_turn_after_restart(
    tmp_path: Path,
) -> None:
    read_service, runtime_paths = _build_read_service(tmp_path)
    old_session_id = "session-before-clear"
    _seed_session(read_service, old_session_id)

    assert read_service.clear_all_sessions() == 1
    read_service.close()

    store = ChatStore(db_path=str(runtime_paths.chat_db_path), runtime_paths=runtime_paths)
    await store.initialize()
    with pytest.raises(
        (ChatTurnConflictError, sqlite3.IntegrityError),
        match="cleared|unavailable",
    ):
        await store.create_user_turn_once(
            session_id=old_session_id,
            user_id="local_user",
            turn_id="turn-retried-after-clear",
            message_text="This response was lost, so the old request retried.",
            created_at_ms=2,
            runtime_envelope={
                "source": "api",
                "user_id": "local_user",
                "session_id": old_session_id,
                "turn_id": "turn-retried-after-clear",
                "message": "This response was lost, so the old request retried.",
                "attachments": [],
                "metadata": {},
            },
            request_fingerprint="retry",
        )

    assert await store._fetchone(  # noqa: SLF001 - persistence invariant check
        "SELECT 1 FROM chat_sessions WHERE session_id = ?",
        (old_session_id,),
    ) is None

    restarted = ChatReadService(runtime_paths=runtime_paths)
    assert restarted.complete_global_clear() is True
    with sqlite3.connect(runtime_paths.chat_db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM chat_cleared_session_scopes"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM chat_cleared_message_scopes"
        ).fetchone()[0] == 0
    restarted.close()

    new_session_id = "session-after-clear"
    await store.create_user_turn_once(
        session_id=new_session_id,
        user_id="local_user",
        turn_id="turn-after-clear",
        message_text="A genuinely new conversation.",
        created_at_ms=3,
        runtime_envelope={
            "source": "api",
            "user_id": "local_user",
            "session_id": new_session_id,
            "turn_id": "turn-after-clear",
            "message": "A genuinely new conversation.",
            "attachments": [],
            "metadata": {},
        },
        request_fingerprint="new",
    )
    assert await store._fetchone(  # noqa: SLF001 - persistence invariant check
        "SELECT 1 FROM chat_sessions WHERE session_id = ?",
        (new_session_id,),
    ) is not None


def test_global_clear_removes_private_bytes_from_chat_database_and_wal(
    tmp_path: Path,
) -> None:
    read_service, runtime_paths = _build_read_service(tmp_path)
    private_marker = "private-chat-marker-that-must-not-survive"
    connection = read_service._get_conn()
    connection.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms
        ) VALUES (?, 'local_user', ?, 1, 1)
        """,
        (private_marker, private_marker),
    )
    connection.commit()
    database_paths = (
        runtime_paths.chat_db_path,
        Path(f"{runtime_paths.chat_db_path}-wal"),
    )
    assert any(
        private_marker.encode() in path.read_bytes()
        for path in database_paths
        if path.exists()
    )

    assert read_service.clear_all_sessions() == 1
    assert read_service.complete_global_clear() is True

    assert all(
        private_marker.encode() not in path.read_bytes()
        for path in database_paths
        if path.exists()
    )
    read_service.close()


@pytest.mark.asyncio
async def test_late_completion_cannot_recreate_a_cleared_session(
    tmp_path: Path,
) -> None:
    read_service, runtime_paths = _build_read_service(tmp_path)
    old_session_id = "session-late-completion"
    _seed_session(read_service, old_session_id)

    assert read_service.clear_all_sessions() == 1

    store = ChatStore(db_path=str(runtime_paths.chat_db_path), runtime_paths=runtime_paths)
    await store.initialize()
    with pytest.raises(sqlite3.IntegrityError, match="session is unavailable"):
        await store.append_completion_message_once(
            ChatMessageRecord(
                message_id="message-late-completion",
                session_id=old_session_id,
                turn_id=None,
                user_id="local_user",
                role="assistant",
                message_kind="assistant_final",
                content_text="Late result",
                payload_json="{}",
                is_final=True,
                is_visible=True,
                created_at_ms=2,
                sequence_no=1,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )

    assert await store._fetchone(  # noqa: SLF001 - persistence invariant check
        "SELECT 1 FROM chat_messages WHERE message_id = ?",
        ("message-late-completion",),
    ) is None


@pytest.mark.asyncio
async def test_deleted_session_cannot_be_revived_by_a_late_upsert(
    tmp_path: Path,
) -> None:
    read_service, runtime_paths = _build_read_service(tmp_path)
    session_id = "session-deleted-before-upsert"
    _seed_session(read_service, session_id)

    read_service.delete_session("local_user", session_id)
    with sqlite3.connect(runtime_paths.chat_db_path) as connection:
        connection.execute(
            """
            DELETE FROM chat_cleared_session_scopes
            WHERE session_id = ?
            """,
            (session_id,),
        )
        connection.commit()
    read_service.delete_session("local_user", session_id)

    store = ChatStore(db_path=str(runtime_paths.chat_db_path), runtime_paths=runtime_paths)
    await store.initialize()
    with pytest.raises(sqlite3.IntegrityError, match="session was cleared"):
        await store.upsert_session(
            ChatSessionRecord(
                session_id=session_id.upper(),
                user_id="local_user",
                title="Late session state",
                title_overridden=False,
                summary="",
                created_at_ms=1,
                updated_at_ms=2,
                last_message_at_ms=None,
                last_user_message_at_ms=None,
                last_message_preview="",
                last_user_message_preview="",
                message_count=0,
                workspace_path=None,
                history_version=0,
                archived_at_ms=None,
                deleted_at_ms=None,
            )
        )

    with sqlite3.connect(runtime_paths.chat_db_path) as connection:
        assert connection.execute(
            """
            SELECT deleted_at_ms
            FROM chat_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()[0] is not None
        assert connection.execute(
            """
            SELECT 1
            FROM chat_cleared_session_scopes
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone() == (1,)
