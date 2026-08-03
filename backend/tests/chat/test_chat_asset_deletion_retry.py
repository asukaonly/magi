from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from _shared.db_schema import apply_chain_schema
from magi.chat.asset_gc import ChatAssetDeletionError, ChatAssetGC
from magi.chat.forgetting import ChatForgettingRecoveryService
from magi.core.chat_cleanup import ChatSurfaceCleanupPendingError
from magi.chat.read.asset_ownership import (
    SHARED_TARGET_ASSET_KEYS_SQL,
    TARGET_ASSET_ROWS_SQL,
    unshared_asset_references,
)
from magi.chat.read_service import ChatReadService
from magi.config.models import ChatAssetsLifecycleSettings
from magi.db.migrations.runtime_trace.versions.v1_initial import (
    SCHEMA_SQL as RUNTIME_TRACE_SCHEMA_SQL,
)
from magi.memory.forgetting import ForgetSelector
from magi.utils.runtime import RuntimePaths


def _build_service(tmp_path: Path) -> tuple[ChatReadService, RuntimePaths]:
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


def _reopen_service(runtime_paths: RuntimePaths) -> ChatReadService:
    service = object.__new__(ChatReadService)
    service._runtime_paths = runtime_paths
    service._chat_db_path = runtime_paths.chat_db_path
    service._l1_db_path = runtime_paths.l1_memory_db_path
    service._runtime_trace_db_path = runtime_paths.runtime_trace_db_path
    service._asset_gc = ChatAssetGC(runtime_paths=runtime_paths)
    service._conn = None
    return service


def _insert_asset_ref(
    conn: sqlite3.Connection,
    runtime_paths: RuntimePaths,
    *,
    message_id: str,
    asset_path: Path,
    asset_kind: str = "attachment",
    created_at_ms: int = 1,
) -> None:
    canonical_path = asset_path.resolve()
    conn.execute(
        """
        INSERT OR REPLACE INTO chat_message_asset_refs(
            message_id, asset_key, storage_rel_path, asset_kind, created_at_ms
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            message_id,
            canonical_path.relative_to(
                runtime_paths.chat_resources_dir.resolve()
            ).as_posix(),
            canonical_path.relative_to(runtime_paths.base_dir.resolve()).as_posix(),
            asset_kind,
            created_at_ms,
        ),
    )


def _seed_chat(
    service: ChatReadService,
    runtime_paths: RuntimePaths,
    *,
    session_id: str,
    message_id: str,
) -> Path:
    turn_id = f"turn-{session_id}"
    attachment_id = f"attachment-{session_id}"
    asset_path = (
        runtime_paths.chat_files_dir
        / session_id
        / turn_id
        / f"{attachment_id}__private.txt"
    )
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text("private attachment", encoding="utf-8")
    storage_rel_path = asset_path.relative_to(runtime_paths.base_dir).as_posix()
    payload_json = json.dumps(
        {
            "attachments": [
                {
                    "attachment_id": attachment_id,
                    "storage_path": storage_rel_path,
                }
            ]
        }
    )

    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms,
            message_count
        ) VALUES (?, 'u1', 'Private chat', 1, 1, 1)
        """,
        (session_id,),
    )
    conn.execute(
        """
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms
        ) VALUES (?, ?, 'u1', 'completed', 'final_only', '{}', 1, 1)
        """,
        (turn_id, session_id),
    )
    conn.execute(
        """
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible,
            created_at_ms, sequence_no
        ) VALUES (?, ?, ?, 'u1', 'user', 'user_text',
                  'private message', ?, 1, 1, 1, 1)
        """,
        (message_id, session_id, turn_id, payload_json),
    )
    conn.execute(
        """
        INSERT INTO chat_attachments(
            attachment_id, session_id, turn_id, message_id, user_id,
            kind, original_name, mime_type, size_bytes,
            storage_rel_path, created_at_ms
        ) VALUES (?, ?, ?, ?, 'u1', 'file', 'private.txt',
                  'text/plain', 18, ?, 1)
        """,
        (attachment_id, session_id, turn_id, message_id, storage_rel_path),
    )
    _insert_asset_ref(
        conn,
        runtime_paths,
        message_id=message_id,
        asset_path=asset_path,
    )
    conn.commit()
    return asset_path


def _seed_new_chat_after_snapshot(
    service: ChatReadService,
    runtime_paths: RuntimePaths,
    *,
    session_id: str,
) -> Path:
    turn_id = f"turn-new-{session_id}"
    message_id = f"message-new-{session_id}"
    attachment_id = f"attachment-new-{session_id}"
    asset_path = (
        runtime_paths.chat_files_dir
        / session_id
        / turn_id
        / f"{attachment_id}__new-private.txt"
    )
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text("new attachment", encoding="utf-8")
    storage_rel_path = asset_path.relative_to(runtime_paths.base_dir).as_posix()

    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms
        ) VALUES (?, ?, 'u1', 'completed', 'final_only', '{}', 2, 2)
        """,
        (turn_id, session_id),
    )
    conn.execute(
        """
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible,
            created_at_ms, sequence_no
        ) VALUES (?, ?, ?, 'u1', 'user', 'user_text',
                  'new private message', '{}', 1, 1, 2, 2)
        """,
        (message_id, session_id, turn_id),
    )
    conn.execute(
        """
        INSERT INTO chat_attachments(
            attachment_id, session_id, turn_id, message_id, user_id,
            kind, original_name, mime_type, size_bytes,
            storage_rel_path, created_at_ms
        ) VALUES (?, ?, ?, ?, 'u1', 'file', 'new-private.txt',
                  'text/plain', 14, ?, 2)
        """,
        (attachment_id, session_id, turn_id, message_id, storage_rel_path),
    )
    _insert_asset_ref(
        conn,
        runtime_paths,
        message_id=message_id,
        asset_path=asset_path,
        created_at_ms=2,
    )
    conn.execute(
        """
        UPDATE chat_sessions
        SET last_message_at_ms = 2,
            last_user_message_at_ms = 2,
            last_message_preview = 'new private message',
            last_user_message_preview = 'new private message',
            message_count = 2
        WHERE session_id = ?
        """,
        (session_id,),
    )
    conn.commit()
    return asset_path


def test_forgotten_message_identity_cannot_be_recreated(tmp_path: Path) -> None:
    service, runtime_paths = _build_service(tmp_path)
    session_id = "session-cleared-message"
    message_id = "message-cleared"
    _seed_chat(
        service,
        runtime_paths,
        session_id=session_id,
        message_id=message_id,
    )

    assert service.forget_message_artifacts("u1", session_id, message_id)

    connection = service._get_conn()
    assert connection.execute(
        """
        SELECT cleared_at_ms
        FROM chat_cleared_message_scopes
        WHERE session_id = ? AND message_id = ?
        """,
        (session_id, message_id),
    ).fetchone() is not None
    with pytest.raises(sqlite3.IntegrityError, match="message was cleared"):
        connection.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, user_id, role, message_kind,
                content_text, created_at_ms, sequence_no
            ) VALUES (?, ?, 'u1', 'assistant', 'assistant_final', 'late', 2, 2)
            """,
            (message_id, session_id),
        )


def test_completed_forget_ledger_can_restore_missing_chat_barriers(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    _seed_chat(
        service,
        runtime_paths,
        session_id="session-ledger",
        message_id="message-ledger",
    )

    result = service.backfill_cleared_chat_scopes(
        ["session-deleted"],
        [("session-ledger", "message-ledger")],
    )

    assert result == {"sessions": 1, "messages": 1}
    connection = service._get_conn()
    assert connection.execute(
        """
        SELECT 1
        FROM chat_cleared_session_scopes
        WHERE session_id = 'session-deleted'
        """
    ).fetchone() is not None
    assert connection.execute(
        """
        SELECT 1
        FROM chat_cleared_message_scopes
        WHERE session_id = 'session-ledger'
          AND message_id = 'message-ledger'
        """
    ).fetchone() is not None
    with pytest.raises(sqlite3.IntegrityError, match="message was cleared"):
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_messages(
                message_id, session_id, user_id, role, message_kind,
                content_text, created_at_ms, sequence_no
            ) VALUES (
                'message-ledger', 'session-ledger', 'u1', 'assistant',
                'assistant_final', 'late', 2, 2
            )
            """
        )
    service.close()


def _retarget_message_asset(
    service: ChatReadService,
    runtime_paths: RuntimePaths,
    *,
    message_id: str,
    asset_path: Path,
) -> Path:
    conn = service._get_conn()
    attachment = conn.execute(
        """
        SELECT attachment_id, storage_rel_path
        FROM chat_attachments
        WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()
    assert attachment is not None
    old_asset_path = runtime_paths.base_dir / str(attachment["storage_rel_path"])
    storage_rel_path = asset_path.relative_to(runtime_paths.base_dir).as_posix()
    conn.execute(
        """
        UPDATE chat_attachments
        SET storage_rel_path = ?
        WHERE message_id = ?
        """,
        (storage_rel_path, message_id),
    )
    conn.execute(
        "DELETE FROM chat_message_asset_refs WHERE message_id = ?",
        (message_id,),
    )
    _insert_asset_ref(
        conn,
        runtime_paths,
        message_id=message_id,
        asset_path=asset_path,
        created_at_ms=2,
    )
    conn.execute(
        """
        UPDATE chat_messages
        SET payload_json = ?
        WHERE message_id = ?
        """,
        (
            json.dumps(
                {
                    "attachments": [
                        {
                            "attachment_id": str(attachment["attachment_id"]),
                            "storage_path": storage_rel_path,
                        }
                    ]
                }
            ),
            message_id,
        ),
    )
    conn.commit()
    return old_asset_path


def _seed_runtime_trace(
    runtime_trace_db_path: Path,
    *,
    session_id: str,
    turn_id: str,
) -> None:
    runtime_trace_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(runtime_trace_db_path)
    conn.executescript(RUNTIME_TRACE_SCHEMA_SQL)
    conn.execute(
        """
        INSERT INTO trace_turns(
            trace_id, turn_id, session_id, user_id, status, mode,
            started_at_ms, user_message_preview, response_preview,
            created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, 'u1', 'completed', 'chat', 1, 'user', 'assistant', 1, 1)
        """,
        (f"trace-{turn_id}", turn_id, session_id),
    )
    conn.execute(
        """
        INSERT INTO trace_llm_calls(
            span_id, trace_id, turn_id, provider, model, request_preview,
            response_preview
        ) VALUES (?, ?, ?, 'test', 'test', 'user', 'assistant')
        """,
        (f"span-{turn_id}", f"trace-{turn_id}", turn_id),
    )
    conn.execute(
        """
        INSERT INTO runtime_notifications(
            channel, user_id, session_id, turn_id, payload_json, created_at_ms
        ) VALUES ('agent_response', 'u1', ?, ?, '{"content":"assistant"}', 1)
        """,
        (session_id, turn_id),
    )
    conn.commit()
    conn.close()


def _runtime_trace_counts(runtime_trace_db_path: Path, *, turn_id: str) -> tuple[int, int, int]:
    conn = sqlite3.connect(runtime_trace_db_path)
    try:
        return (
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM trace_turns WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()[0]
            ),
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM trace_llm_calls WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()[0]
            ),
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM runtime_notifications WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()[0]
            ),
        )
    finally:
        conn.close()


def _fail_once(monkeypatch: pytest.MonkeyPatch, target: object, method_name: str) -> None:
    original = getattr(target, method_name)
    attempts = 0

    def flaky(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ChatAssetDeletionError("simulated managed asset delete failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(target, method_name, flaky)


class _CommitFailingConnection:
    def __init__(self, connection: sqlite3.Connection, *, fail_on: int = 1) -> None:
        self._connection = connection
        self._commit_count = 0
        self._fail_on = fail_on

    def commit(self) -> None:
        self._commit_count += 1
        if self._commit_count == self._fail_on:
            raise sqlite3.OperationalError("simulated chat commit failure")
        self._connection.commit()

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self._connection, name)


@pytest.mark.parametrize(
    "operation",
    ("session", "message", "history", "global"),
)
def test_chat_deletion_commit_failure_never_precedes_external_asset_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    session_id = f"session-commit-{operation}"
    message_id = f"message-commit-{operation}"
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id=session_id,
        message_id=message_id,
    )
    original_get_conn = service._get_conn
    connection = original_get_conn()
    failing_connection = _CommitFailingConnection(connection)
    monkeypatch.setattr(service, "_get_conn", lambda: failing_connection)

    def run_operation() -> None:
        if operation == "session":
            service.delete_session("u1", session_id)
        elif operation == "message":
            service.forget_message_artifacts("u1", session_id, message_id)
        elif operation == "history":
            service.clear_conversation_history("u1", session_id)
        else:
            service.clear_all_sessions()

    with pytest.raises(sqlite3.OperationalError, match="simulated chat commit failure"):
        run_operation()

    monkeypatch.setattr(service, "_get_conn", original_get_conn)
    assert asset_path.exists()
    assert connection.execute(
        "SELECT deleted_at_ms FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0] is None
    assert tuple(
        connection.execute(
            """
            SELECT content_text, is_visible
            FROM chat_messages
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
    ) == ("private message", 1)
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_attachments WHERE message_id = ?",
        (message_id,),
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs WHERE message_id = ?",
        (message_id,),
    ).fetchone()[0] == 1

    run_operation()

    assert not asset_path.exists()
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_attachments WHERE message_id = ?",
        (message_id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs WHERE message_id = ?",
        (message_id,),
    ).fetchone()[0] == 0
    service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("message", "history"))
async def test_pending_forget_surface_recovers_after_second_phase_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    session_id = f"session-second-phase-{operation}"
    message_id = f"message-second-phase-{operation}"
    turn_id = f"turn-{session_id}"
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id=session_id,
        message_id=message_id,
    )
    original_get_conn = service._get_conn
    connection = original_get_conn()
    failing_connection = _CommitFailingConnection(connection, fail_on=2)
    monkeypatch.setattr(service, "_get_conn", lambda: failing_connection)

    with pytest.raises(ChatSurfaceCleanupPendingError) as exc_info:
        if operation == "message":
            service.forget_message_artifacts("u1", session_id, message_id)
        else:
            service.clear_conversation_history_snapshot(
                "u1",
                session_id,
                [message_id],
                [turn_id],
            )
    assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)
    assert "simulated chat commit failure" in str(exc_info.value.__cause__)

    monkeypatch.setattr(service, "_get_conn", original_get_conn)
    assert not asset_path.exists()
    assert tuple(
        connection.execute(
            "SELECT content_text, payload_json, is_visible "
            "FROM chat_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    ) == ("", "{}", 0)
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs WHERE message_id = ?",
        (message_id,),
    ).fetchone()[0] == 1

    selector = (
        ForgetSelector.chat_message(
            user_id="u1",
            session_id=session_id,
            message_id=message_id,
            turn_id=turn_id,
            source="chat",
            event_type="UserMessage",
        )
        if operation == "message"
        else ForgetSelector.chat_history(
            user_id="u1",
            session_id=session_id,
            turn_ids=[turn_id],
            messages=[
                {
                    "message_id": message_id,
                    "source_message_id": message_id,
                    "turn_id": turn_id,
                    "source": "chat",
                    "event_type": "UserMessage",
                }
            ],
            surface_message_ids=[message_id],
        )
    )
    pending_operation = type(
        "_PendingOperation",
        (),
        {"operation_id": f"forget-{operation}", "selector": selector},
    )()

    class _Memory:
        def __init__(self) -> None:
            self.pending = [pending_operation]
            self.finalized: list[str] = []

        @asynccontextmanager
        async def chat_forget_operation_guard(self):  # type: ignore[no-untyped-def]
            yield

        async def list_chat_forget_intents_awaiting_runtime_barriers(self):  # type: ignore[no-untyped-def]
            return []

        async def list_pending_chat_surface_finalizations(self):  # type: ignore[no-untyped-def]
            return list(self.pending)

        async def mark_chat_surface_finalized(self, operation_id: str) -> None:
            self.finalized.append(operation_id)
            self.pending = []

    class _Runtime:
        @asynccontextmanager
        async def forget_operation_boundary(self):  # type: ignore[no-untyped-def]
            yield

        async def prepare_message_delete(self, **_scope):  # type: ignore[no-untyped-def]
            return object()

        async def prepare_history_clear(self, **_scope):  # type: ignore[no-untyped-def]
            return object()

    memory = _Memory()
    recovery = ChatForgettingRecoveryService(
        chat_read_service=service,
        memory=memory,
        runtime=_Runtime(),
    )

    assert await recovery.recover_pending() == {
        "intents_found": 0,
        "intents_activated": 0,
        "surfaces_found": 1,
        "surfaces_completed": 1,
    }
    assert memory.finalized == [f"forget-{operation}"]
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE message_id = ?",
        (message_id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs WHERE message_id = ?",
        (message_id,),
    ).fetchone()[0] == 0
    service.close()


def test_session_delete_failure_redacts_chat_and_keeps_private_retry_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-delete",
        message_id="message-delete",
    )
    _fail_once(monkeypatch, service._asset_gc, "delete_message_assets")

    with pytest.raises(ChatSurfaceCleanupPendingError):
        service.delete_session("u1", "session-delete")

    conn = service._get_conn()
    assert asset_path.exists()
    assert conn.execute(
        "SELECT deleted_at_ms FROM chat_sessions WHERE session_id = 'session-delete'"
    ).fetchone()[0] is not None
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-delete'"
        ).fetchone()[0]
        == 0
    )
    assert tuple(
        conn.execute(
            "SELECT content_text, payload_json, is_visible "
            "FROM chat_messages WHERE message_id = 'message-delete'"
        ).fetchone()
    ) == ("", "{}", 0)
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs "
        "WHERE message_id = 'message-delete'"
    ).fetchone()[0] == 1

    service.delete_session("u1", "session-delete")

    assert not asset_path.exists()
    assert (
        conn.execute(
            "SELECT deleted_at_ms FROM chat_sessions WHERE session_id = 'session-delete'"
        ).fetchone()[0]
        is not None
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-delete'"
        ).fetchone()[0]
        == 0
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs "
        "WHERE message_id = 'message-delete'"
    ).fetchone()[0] == 0
    service.close()


def test_session_delete_preserves_asset_owned_by_another_active_session(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    shared_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-delete-owner",
        message_id="message-delete-owner",
    )
    _seed_chat(
        service,
        runtime_paths,
        session_id="session-delete-survivor",
        message_id="message-delete-survivor",
    )
    replaced_asset = _retarget_message_asset(
        service,
        runtime_paths,
        message_id="message-delete-survivor",
        asset_path=shared_asset,
    )
    replaced_asset.unlink()

    service.delete_session("u1", "session-delete-owner")

    assert shared_asset.exists()
    assert (
        service._get_conn()
        .execute(
            """
            SELECT 1
            FROM chat_attachments
            WHERE attachment_id = 'attachment-session-delete-survivor'
            """
        )
        .fetchone()
        is not None
    )
    conn = service._get_conn()
    assert [
        str(row["message_id"])
        for row in conn.execute(
            """
            SELECT message_id
            FROM chat_message_asset_refs
            WHERE asset_key = ?
            """,
            (
                shared_asset.resolve()
                .relative_to(runtime_paths.chat_resources_dir.resolve())
                .as_posix(),
            ),
        ).fetchall()
    ] == ["message-delete-survivor"]

    sweep = ChatAssetGC(
        runtime_paths=runtime_paths,
        now=lambda: 10**12,
    ).sweep_orphan_assets(orphan_grace_hours=0)
    assert sweep["chat_asset_orphan_files_deleted"] == 0
    assert shared_asset.exists()
    service.close()


def test_history_clear_failure_redacts_metadata_and_keeps_private_retry_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-clear",
        message_id="message-clear",
    )
    _fail_once(monkeypatch, service._asset_gc, "delete_message_assets")

    with pytest.raises(ChatSurfaceCleanupPendingError):
        service.clear_conversation_history("u1", "session-clear")

    conn = service._get_conn()
    assert asset_path.exists()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 0
    )
    assert tuple(
        conn.execute(
            "SELECT content_text, payload_json, is_visible "
            "FROM chat_messages WHERE message_id = 'message-clear'"
        ).fetchone()
    ) == ("", "{}", 0)
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs "
        "WHERE message_id = 'message-clear'"
    ).fetchone()[0] == 1

    service.clear_conversation_history("u1", "session-clear")

    assert not asset_path.exists()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE session_id = 'session-clear'"
        ).fetchone()[0]
        == 0
    )
    service.close()


def test_history_snapshot_recovery_physically_removes_only_the_old_transcript(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    old_asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-recovery",
        message_id="message-recovery",
    )
    old_turn_id = "turn-session-recovery"
    orphan_old_asset = (
        runtime_paths.chat_derived_dir / "session-recovery" / old_turn_id / "orphan-private.txt"
    )
    orphan_old_asset.parent.mkdir(parents=True, exist_ok=True)
    orphan_old_asset.write_text("old derived content", encoding="utf-8")
    new_asset_path = _seed_new_chat_after_snapshot(
        service,
        runtime_paths,
        session_id="session-recovery",
    )

    service.clear_conversation_history_snapshot(
        "u1",
        "session-recovery",
        ["message-recovery"],
        [old_turn_id],
    )

    conn = service._get_conn()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE message_id = 'message-recovery'"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_turns WHERE turn_id = ?",
            (old_turn_id,),
        ).fetchone()[0]
        == 0
    )
    assert tuple(
        conn.execute("""
            SELECT content_text, is_visible
            FROM chat_messages
            WHERE message_id = 'message-new-session-recovery'
            """).fetchone()
    ) == ("new private message", 1)
    assert not old_asset_path.exists()
    assert not orphan_old_asset.exists()
    assert new_asset_path.exists()

    history_version = conn.execute(
        "SELECT history_version FROM chat_sessions WHERE session_id = 'session-recovery'"
    ).fetchone()[0]
    service.clear_conversation_history_snapshot(
        "u1",
        "session-recovery",
        ["message-recovery"],
        [old_turn_id],
    )
    assert (
        conn.execute(
            "SELECT history_version FROM chat_sessions WHERE session_id = 'session-recovery'"
        ).fetchone()[0]
        == history_version
    )
    service.close()


def test_empty_active_session_history_clear_removes_bounded_orphan_assets(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms
        ) VALUES ('session-empty-orphan', 'u1', 'empty', 1, 1)
        """
    )
    conn.commit()
    orphan_asset = (
        runtime_paths.chat_files_dir
        / "session-empty-orphan"
        / "turn-never-committed"
        / "orphan.txt"
    )
    orphan_asset.parent.mkdir(parents=True, exist_ok=True)
    orphan_asset.write_text("orphan", encoding="utf-8")

    service.clear_conversation_history("u1", "session-empty-orphan")

    assert not orphan_asset.exists()
    history_version = conn.execute(
        """
        SELECT history_version
        FROM chat_sessions
        WHERE session_id = 'session-empty-orphan'
        """
    ).fetchone()[0]
    service.clear_conversation_history("u1", "session-empty-orphan")
    assert conn.execute(
        """
        SELECT history_version
        FROM chat_sessions
        WHERE session_id = 'session-empty-orphan'
        """
    ).fetchone()[0] == history_version
    service.close()


def test_history_snapshot_preserves_asset_owned_by_same_session_survivor(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    shared_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-history-survivor",
        message_id="message-history-target",
    )
    _seed_new_chat_after_snapshot(
        service,
        runtime_paths,
        session_id="session-history-survivor",
    )
    replaced_asset = _retarget_message_asset(
        service,
        runtime_paths,
        message_id="message-new-session-history-survivor",
        asset_path=shared_asset,
    )
    replaced_asset.unlink()

    service.clear_conversation_history_snapshot(
        "u1",
        "session-history-survivor",
        ["message-history-target"],
        ["turn-session-history-survivor"],
    )

    assert shared_asset.exists()
    assert (
        service._get_conn()
        .execute(
            """
            SELECT 1
            FROM chat_attachments
            WHERE attachment_id = 'attachment-new-session-history-survivor'
            """
        )
        .fetchone()
        is not None
    )
    service.close()


def test_full_history_clear_preserves_asset_owned_by_another_active_session(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    shared_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-history-owner",
        message_id="message-history-owner",
    )
    _seed_chat(
        service,
        runtime_paths,
        session_id="session-history-other",
        message_id="message-history-other",
    )
    replaced_asset = _retarget_message_asset(
        service,
        runtime_paths,
        message_id="message-history-other",
        asset_path=shared_asset,
    )
    replaced_asset.unlink()

    service.clear_conversation_history("u1", "session-history-owner")

    assert shared_asset.exists()
    assert (
        service._get_conn()
        .execute(
            """
            SELECT 1
            FROM chat_attachments
            WHERE attachment_id = 'attachment-session-history-other'
            """
        )
        .fetchone()
        is not None
    )
    service.close()


def test_clear_all_asset_failure_keeps_only_private_retry_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-clear-all",
        message_id="message-clear-all",
    )
    _fail_once(monkeypatch, service._asset_gc, "clear_all_assets")

    with pytest.raises(ChatAssetDeletionError):
        service.clear_all_sessions()

    conn = service._get_conn()
    assert asset_path.exists()
    assert conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_sessions WHERE deleted_at_ms IS NOT NULL"
    ).fetchone()[0] == 1
    assert tuple(
        conn.execute(
            "SELECT content_text, payload_json, is_visible "
            "FROM chat_messages WHERE message_id = 'message-clear-all'"
        ).fetchone()
    ) == ("", "{}", 0)
    assert conn.execute("SELECT COUNT(*) FROM chat_attachments").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs"
    ).fetchone()[0] == 1

    assert service.clear_all_sessions() == 1
    assert not asset_path.exists()
    for table_name in (
        "chat_sessions",
        "chat_messages",
        "chat_attachments",
        "chat_message_asset_refs",
    ):
        assert conn.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0] == 0
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM chat_cleared_session_scopes
        WHERE session_id = 'session-clear-all'
        """
    ).fetchone()[0] == 1
    service.close()


def test_clear_all_sessions_always_deletes_managed_assets(tmp_path: Path) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-clear-unconditional",
        message_id="message-clear-unconditional",
    )

    assert service.clear_all_sessions() == 1

    assert not asset_path.exists()
    assert "delete_on_clear_memory" not in ChatAssetsLifecycleSettings.model_fields
    service.close()


@pytest.mark.asyncio
async def test_interrupted_global_clear_recovers_immediately_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-global-crash",
        message_id="message-global-crash",
    )
    _fail_once(monkeypatch, service._asset_gc, "clear_all_assets")

    with pytest.raises(ChatAssetDeletionError):
        service.clear_all_sessions()

    connection = service._get_conn()
    assert asset_path.exists()
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_global_clear_intent"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs"
    ).fetchone()[0] == 1
    service.close()

    restarted = _reopen_service(runtime_paths)
    assert await restarted.arecover_interrupted_global_clear() is True

    assert not asset_path.exists()
    connection = restarted._get_conn()
    for table_name in (
        "chat_sessions",
        "chat_messages",
        "chat_attachments",
        "chat_message_asset_refs",
    ):
        assert connection.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_global_clear_intent"
    ).fetchone()[0] == 1
    assert connection.execute(
        """
        SELECT COUNT(*)
        FROM chat_cleared_session_scopes
        WHERE session_id = 'session-global-crash'
        """
    ).fetchone()[0] == 1
    assert await restarted.arecover_interrupted_global_clear() is True
    assert await restarted.acomplete_global_clear() is True
    assert connection.execute(
        "SELECT COUNT(*) FROM chat_global_clear_intent"
    ).fetchone()[0] == 0
    assert await restarted.arecover_interrupted_global_clear() is False
    restarted.close()


def test_history_snapshot_asset_failure_keeps_old_rows_for_recovery_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    old_asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-snapshot-retry",
        message_id="message-snapshot-retry",
    )
    new_asset_path = _seed_new_chat_after_snapshot(
        service,
        runtime_paths,
        session_id="session-snapshot-retry",
    )
    _fail_once(
        monkeypatch,
        service._asset_gc,
        "delete_message_assets",
    )

    with pytest.raises(ChatSurfaceCleanupPendingError):
        service.clear_conversation_history_snapshot(
            "u1",
            "session-snapshot-retry",
            ["message-snapshot-retry"],
            ["turn-session-snapshot-retry"],
        )

    conn = service._get_conn()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE message_id = 'message-snapshot-retry'"
        ).fetchone()[0]
        == 1
    )
    assert old_asset_path.exists()
    assert new_asset_path.exists()

    service.clear_conversation_history_snapshot(
        "u1",
        "session-snapshot-retry",
        ["message-snapshot-retry"],
        ["turn-session-snapshot-retry"],
    )

    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE message_id = 'message-snapshot-retry'"
        ).fetchone()[0]
        == 0
    )
    assert not old_asset_path.exists()
    assert new_asset_path.exists()
    service.close()


def test_history_snapshot_discovery_failure_rolls_back_chat_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    _seed_chat(
        service,
        runtime_paths,
        session_id="session-discovery-rollback",
        message_id="message-discovery-rollback",
    )

    def fail_discovery(**_kwargs: object) -> list[tuple[str, str]]:
        raise ChatAssetDeletionError("simulated snapshot discovery failure")

    monkeypatch.setattr(
        service,
        "_list_chat_snapshot_asset_references",
        fail_discovery,
    )
    with pytest.raises(ChatAssetDeletionError):
        service.clear_conversation_history(
            "u1",
            "session-discovery-rollback",
        )

    conn = service._get_conn()
    assert conn.in_transaction is False
    conn.execute(
        """
        UPDATE chat_sessions
        SET title = 'write-after-failure'
        WHERE session_id = 'session-discovery-rollback'
        """
    )
    conn.commit()
    assert conn.execute(
        """
        SELECT title
        FROM chat_sessions
        WHERE session_id = 'session-discovery-rollback'
        """
    ).fetchone()[0] == "write-after-failure"
    service.close()


def test_history_clear_rejects_retargeted_session_directory_symlink(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms
        ) VALUES ('session-directory-link', 'u1', 'linked', 1, 1)
        """
    )
    conn.commit()
    survivor_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-directory-survivor",
        message_id="message-directory-survivor",
    )
    linked_session_dir = runtime_paths.chat_files_dir / "session-directory-link"
    linked_session_dir.symlink_to(
        survivor_asset.parents[1],
        target_is_directory=True,
    )

    with pytest.raises(
        ChatAssetDeletionError,
        match="snapshot directory identity changed",
    ):
        service.clear_conversation_history("u1", "session-directory-link")

    assert survivor_asset.exists()
    assert conn.in_transaction is False
    service.close()


def test_message_delete_failure_redacts_content_and_keeps_exact_retry_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-message",
        message_id="message-exact",
    )
    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_user_turn_delivery(
            turn_id, projection_completed, delivery_attempt_no,
            delivery_state, current_command_id,
            runtime_envelope_json, request_fingerprint,
            created_at_ms, updated_at_ms
        ) VALUES (
            'turn-session-message', 1, 0, 'terminal', NULL,
            '{"message":"private message"}', 'fingerprint', 1, 1
        )
        """
    )
    conn.commit()
    _fail_once(monkeypatch, service._asset_gc, "delete_message_assets")

    with pytest.raises(ChatSurfaceCleanupPendingError):
        service.forget_message_artifacts("u1", "session-message", "message-exact")

    row = conn.execute(
        "SELECT content_text, payload_json, is_visible "
        "FROM chat_messages WHERE message_id = 'message-exact'"
    ).fetchone()
    assert asset_path.exists()
    assert tuple(row) == ("", "{}", 0)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE message_id = 'message-exact'"
        ).fetchone()[0]
        == 0
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs "
        "WHERE message_id = 'message-exact'"
    ).fetchone()[0] == 1
    assert (
        conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-session-message'
            """
        ).fetchone()[0]
        == 0
    )

    assert service.forget_message_artifacts("u1", "session-message", "message-exact")

    assert not asset_path.exists()
    assert conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE message_id = 'message-exact'"
    ).fetchone()[0] == 0
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM chat_attachments WHERE message_id = 'message-exact'"
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-session-message'
            """
        ).fetchone()[0]
        == 0
    )
    service.close()


def test_message_delete_recovers_after_file_removal_precedes_chat_commit(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-file-first",
        message_id="message-file-first",
    )
    conn = service._get_conn()
    asset_references = unshared_asset_references(
        conn,
        message_ids=["message-file-first"],
    )
    conn.commit()

    assert service._asset_gc.delete_message_assets(asset_references) == 1
    assert not asset_path.exists()

    assert service.forget_message_artifacts(
        "u1",
        "session-file-first",
        "message-file-first",
    )
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM chat_messages
        WHERE message_id = 'message-file-first'
        """
    ).fetchone()[0] == 0
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM chat_attachments
        WHERE message_id = 'message-file-first'
        """
    ).fetchone()[0] == 0
    service.close()


def test_message_delete_uses_indexed_owner_queries_without_reading_payloads(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    _seed_chat(
        service,
        runtime_paths,
        session_id="session-query-scope",
        message_id="message-query-scope",
    )
    conn = service._get_conn()
    conn.execute("BEGIN IMMEDIATE")
    unshared_asset_references(
        conn,
        message_ids=["message-query-scope"],
    )
    target_plan = [
        str(row[3])
        for row in conn.execute(f"EXPLAIN QUERY PLAN {TARGET_ASSET_ROWS_SQL}").fetchall()
    ]
    shared_plan = [
        str(row[3])
        for row in conn.execute(
            f"EXPLAIN QUERY PLAN {SHARED_TARGET_ASSET_KEYS_SQL}"
        ).fetchall()
    ]
    conn.rollback()

    assert any("SEARCH refs USING INDEX" in detail for detail in target_plan)
    assert not any("SCAN refs" in detail for detail in target_plan)
    assert any(
        "SEARCH owner USING" in detail
        and "idx_chat_message_asset_refs_asset_key" in detail
        for detail in shared_plan
    ), shared_plan
    assert not any("SCAN owner" in detail for detail in shared_plan)

    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        assert service.forget_message_artifacts(
            "u1",
            "session-query-scope",
            "message-query-scope",
        )
    finally:
        conn.set_trace_callback(None)
    assert not any(
        statement.lstrip().upper().startswith("SELECT")
        and "PAYLOAD_JSON" in statement.upper()
        for statement in statements
    )
    service.close()


def test_user_message_delete_removes_its_turn_runtime_trace(tmp_path: Path) -> None:
    service, runtime_paths = _build_service(tmp_path)
    _seed_chat(
        service,
        runtime_paths,
        session_id="session-user-trace",
        message_id="message-user-trace",
    )
    turn_id = "turn-session-user-trace"
    _seed_runtime_trace(
        runtime_paths.runtime_trace_db_path,
        session_id="session-user-trace",
        turn_id=turn_id,
    )

    assert service.forget_message_artifacts(
        "u1",
        "session-user-trace",
        "message-user-trace",
    )

    assert _runtime_trace_counts(
        runtime_paths.runtime_trace_db_path,
        turn_id=turn_id,
    ) == (0, 0, 0)
    service.close()


def test_assistant_message_delete_preserves_shared_turn_runtime_trace(tmp_path: Path) -> None:
    service, runtime_paths = _build_service(tmp_path)
    _seed_chat(
        service,
        runtime_paths,
        session_id="session-assistant-trace",
        message_id="message-assistant-trace",
    )
    conn = service._get_conn()
    conn.execute(
        """
        UPDATE chat_messages
        SET role = 'assistant', message_kind = 'assistant_final'
        WHERE message_id = 'message-assistant-trace'
        """
    )
    conn.commit()
    turn_id = "turn-session-assistant-trace"
    _seed_runtime_trace(
        runtime_paths.runtime_trace_db_path,
        session_id="session-assistant-trace",
        turn_id=turn_id,
    )

    assert service.forget_message_artifacts(
        "u1",
        "session-assistant-trace",
        "message-assistant-trace",
    )

    assert _runtime_trace_counts(
        runtime_paths.runtime_trace_db_path,
        turn_id=turn_id,
    ) == (1, 1, 1)
    service.close()


def test_message_delete_keeps_file_until_the_last_message_owner_is_removed(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-shared",
        message_id="message-first",
    )
    storage_rel_path = asset_path.relative_to(runtime_paths.base_dir).as_posix()
    sibling_payload = json.dumps(
        {
            "attachments": [
                {
                    "attachment_id": "attachment-sibling",
                    "storage_path": storage_rel_path,
                }
            ]
        }
    )
    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms
        ) VALUES (
            'turn-sibling', 'session-shared', 'u1', 'completed',
            'final_only', '{}', 2, 2
        )
        """
    )
    conn.execute(
        """
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible,
            created_at_ms, sequence_no
        ) VALUES (
            'message-sibling', 'session-shared', 'turn-sibling', 'u1',
            'user', 'user_text', 'keep this message', ?, 1, 1, 2, 2
        )
        """,
        (sibling_payload,),
    )
    conn.execute(
        """
        INSERT INTO chat_attachments(
            attachment_id, session_id, turn_id, message_id, user_id,
            kind, original_name, mime_type, size_bytes,
            storage_rel_path, created_at_ms
        ) VALUES (
            'attachment-sibling', 'session-shared', 'turn-sibling',
            'message-sibling', 'u1', 'file', 'shared.txt',
            'text/plain', 18, ?, 2
        )
        """,
        (storage_rel_path,),
    )
    _insert_asset_ref(
        conn,
        runtime_paths,
        message_id="message-sibling",
        asset_path=asset_path,
        created_at_ms=2,
    )
    conn.commit()

    assert service.forget_message_artifacts(
        "u1",
        "session-shared",
        "message-first",
    )
    assert asset_path.exists()
    assert (
        service._get_conn()
        .execute(
            """
            SELECT 1
            FROM chat_attachments
            WHERE attachment_id = 'attachment-sibling'
            """
        )
        .fetchone()
        is not None
    )
    assert not service.forget_message_artifacts(
        "u1",
        "session-shared",
        "message-first",
    )
    assert asset_path.exists()
    service.close()

    recovered_service, _ = _build_service(tmp_path)
    assert (
        recovered_service._get_conn()
        .execute(
            """
            SELECT 1
            FROM chat_attachments
            WHERE attachment_id = 'attachment-sibling'
            """
        )
        .fetchone()
        is not None
    )
    assert recovered_service.forget_message_artifacts(
        "u1",
        "session-shared",
        "message-sibling",
    )
    assert not asset_path.exists()
    recovered_service.close()


def test_message_delete_keeps_file_owned_by_another_active_session(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    shared_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-first",
        message_id="message-first",
    )
    replaced_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-second",
        message_id="message-second",
    )
    shared_rel_path = shared_path.relative_to(runtime_paths.base_dir).as_posix()
    conn = service._get_conn()
    conn.execute(
        """
        UPDATE chat_attachments
        SET storage_rel_path = ?
        WHERE message_id = 'message-second'
        """,
        (shared_rel_path,),
    )
    conn.execute(
        """
        DELETE FROM chat_message_asset_refs
        WHERE message_id = 'message-second' AND asset_kind = 'attachment'
        """
    )
    _insert_asset_ref(
        conn,
        runtime_paths,
        message_id="message-second",
        asset_path=shared_path,
        created_at_ms=1,
    )
    conn.execute(
        """
        UPDATE chat_messages
        SET payload_json = ?
        WHERE message_id = 'message-second'
        """,
        (
            json.dumps(
                {
                    "attachments": [
                        {
                            "attachment_id": "attachment-session-second",
                            "storage_path": shared_rel_path,
                        }
                    ]
                }
            ),
        ),
    )
    conn.commit()
    replaced_path.unlink()

    assert service.forget_message_artifacts(
        "u1",
        "session-first",
        "message-first",
    )
    assert shared_path.exists()
    service.close()

    recovered_service, _ = _build_service(tmp_path)
    assert recovered_service.forget_message_artifacts(
        "u1",
        "session-second",
        "message-second",
    )
    assert not shared_path.exists()
    recovered_service.close()


def test_message_delete_respects_canonical_alias_owner(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    shared_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-owner",
        message_id="message-owner",
    )
    replaced_path = _seed_chat(
        service,
        runtime_paths,
        session_id="session-payload",
        message_id="message-payload",
    )
    alias_path = (
        runtime_paths.chat_files_dir
        / "session-payload"
        / "turn-session-payload"
        / "shared-alias.txt"
    )
    alias_path.symlink_to(shared_path)
    alias_rel_path = alias_path.relative_to(runtime_paths.base_dir).as_posix()
    conn = service._get_conn()
    conn.execute(
        "DELETE FROM chat_attachments WHERE message_id = 'message-payload'"
    )
    conn.execute(
        """
        DELETE FROM chat_message_asset_refs
        WHERE message_id = 'message-payload' AND asset_kind = 'attachment'
        """
    )
    _insert_asset_ref(
        conn,
        runtime_paths,
        message_id="message-payload",
        asset_path=alias_path,
        created_at_ms=1,
    )
    conn.execute(
        """
        UPDATE chat_messages
        SET payload_json = ?
        WHERE message_id = 'message-payload'
        """,
        (
            json.dumps(
                {
                    "attachments": [
                        {
                            "attachment_id": "payload-only",
                            "storage_path": alias_rel_path,
                        }
                    ]
                }
            ),
        ),
    )
    conn.commit()
    replaced_path.unlink()

    assert service.forget_message_artifacts(
        "u1",
        "session-owner",
        "message-owner",
    )
    assert shared_path.exists()
    service.close()

    recovered_service = _reopen_service(runtime_paths)
    assert recovered_service.forget_message_artifacts(
        "u1",
        "session-payload",
        "message-payload",
    )
    assert not shared_path.exists()
    recovered_service.close()


def test_message_delete_never_follows_a_retargeted_asset_symlink(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    replaced_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-retargeted",
        message_id="message-retargeted",
    )
    survivor_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-retarget-survivor",
        message_id="message-retarget-survivor",
    )
    replaced_asset.unlink()
    replaced_asset.symlink_to(survivor_asset)

    assert service.forget_message_artifacts(
        "u1",
        "session-retargeted",
        "message-retargeted",
    )

    assert not replaced_asset.exists()
    assert not replaced_asset.is_symlink()
    assert survivor_asset.exists()
    assert (
        service.get_attachment_payload(
            "u1",
            "session-retarget-survivor",
            "attachment-session-retarget-survivor",
        )
        is not None
    )
    service.close()


def test_message_delete_rejects_a_retargeted_parent_directory_symlink(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    replaced_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-parent-retargeted",
        message_id="message-parent-retargeted",
    )
    survivor_asset = _seed_chat(
        service,
        runtime_paths,
        session_id="session-parent-survivor",
        message_id="message-parent-survivor",
    )
    survivor_alias = survivor_asset.with_name(replaced_asset.name)
    survivor_asset.rename(survivor_alias)
    _retarget_message_asset(
        service,
        runtime_paths,
        message_id="message-parent-survivor",
        asset_path=survivor_alias,
    )
    replaced_parent = replaced_asset.parent
    replaced_asset.unlink()
    replaced_parent.rmdir()
    replaced_parent.symlink_to(survivor_alias.parent, target_is_directory=True)

    with pytest.raises(ChatSurfaceCleanupPendingError) as exc_info:
        service.forget_message_artifacts(
            "u1",
            "session-parent-retargeted",
            "message-parent-retargeted",
        )
    assert isinstance(exc_info.value.__cause__, ChatAssetDeletionError)
    assert "identity changed before deletion" in str(exc_info.value.__cause__)

    assert survivor_alias.exists()
    assert (
        service._get_conn()
        .execute(
            """
            SELECT is_visible
            FROM chat_messages
            WHERE message_id = 'message-parent-retargeted'
            """
        )
        .fetchone()[0]
        == 0
    )
    assert service._get_conn().execute(
        "SELECT COUNT(*) FROM chat_message_asset_refs "
        "WHERE message_id = 'message-parent-retargeted'"
    ).fetchone()[0] == 1
    service.close()


def test_explicit_delete_is_strict_but_orphan_sweep_is_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    asset_path = runtime_paths.chat_files_dir / "orphan-session" / "turn-1" / "private.txt"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text("private", encoding="utf-8")
    gc = ChatAssetGC(runtime_paths=runtime_paths, now=lambda: 10**12)

    def fail_delete(_path: Path) -> None:
        raise PermissionError("simulated filesystem denial")

    monkeypatch.setattr("magi.chat.asset_gc.shutil.rmtree", fail_delete)

    with pytest.raises(ChatAssetDeletionError):
        gc.delete_session_assets("orphan-session")

    result = gc.sweep_orphan_assets(orphan_grace_hours=0)

    assert result["chat_asset_orphan_sessions_deleted"] == 0
    assert result["chat_asset_orphan_files_deleted"] == 0
    assert asset_path.exists()


def test_message_delete_fails_closed_for_case_colliding_active_sessions(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    asset_path = _seed_chat(
        service,
        runtime_paths,
        session_id="Case-Session",
        message_id="message-case-session",
    )
    conn = service._get_conn()
    conn.execute("DROP INDEX uq_chat_sessions_session_id_nocase")
    conn.execute("DROP TRIGGER trg_chat_sessions_reject_cleared_session")
    conn.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms
        ) VALUES ('case-session', 'u2', 'Collision', 2, 2)
        """
    )
    conn.commit()

    with pytest.raises(
        ChatAssetDeletionError,
        match="asset scope is ambiguous",
    ):
        service.forget_message_artifacts(
            "u1",
            "Case-Session",
            "message-case-session",
        )

    assert asset_path.exists()
    assert (
        service._get_conn()
        .execute(
            """
            SELECT is_visible
            FROM chat_messages
            WHERE message_id = 'message-case-session'
            """
        )
        .fetchone()[0]
        == 1
    )
    service.close()
