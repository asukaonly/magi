from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from _shared.db_schema import apply_chain_schema
from magi.chat import ChatMessageRecord, ChatStore
from magi.chat.code_delegation_artifacts import (
    ChatCodeDelegationArtifactRegistry,
)
from magi.chat.read_service import ChatReadService
from magi.core.chat_cleanup import ChatSurfaceCleanupPendingError
from magi.core.code_agent_artifacts import CodeAgentDelegationReference
from magi.utils.runtime import RuntimePaths


class _RecordingCodeAgentArtifactGC:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[list[CodeAgentDelegationReference]] = []

    def delete_references(
        self,
        references: list[CodeAgentDelegationReference],
    ) -> int:
        self.calls.append(list(references))
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("injected private cleanup failure")
        return len(references)


def _build_service(tmp_path: Path) -> tuple[ChatReadService, RuntimePaths]:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    apply_chain_schema("chat", runtime_paths.chat_db_path)
    return ChatReadService(runtime_paths=runtime_paths), runtime_paths


def _seed_session(
    service: ChatReadService,
    *,
    session_id: str,
    workspace_path: str | None = None,
) -> None:
    service._get_conn().execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms,
            message_count, workspace_path
        ) VALUES (?, 'u1', 'Private chat', 1, 1, 0, ?)
        """,
        (session_id, workspace_path),
    )
    service._get_conn().commit()


def _seed_turn(
    service: ChatReadService,
    *,
    session_id: str,
    turn_id: str,
    created_at_ms: int = 1,
) -> None:
    service._get_conn().execute(
        """
        INSERT INTO chat_turns(
            turn_id, session_id, user_id, status, response_mode,
            ux_plan_json, created_at_ms, updated_at_ms
        ) VALUES (?, ?, 'u1', 'completed', 'final_only', '{}', ?, ?)
        """,
        (turn_id, session_id, created_at_ms, created_at_ms),
    )
    service._get_conn().commit()


def _seed_message(
    service: ChatReadService,
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    role: str = "assistant",
    delegation_id: str | None = None,
    workspace_path: str | None = None,
    created_at_ms: int = 1,
    sequence_no: int = 1,
) -> None:
    payload: dict[str, object] = {}
    if delegation_id is not None:
        assert workspace_path is not None
        payload["code_agent_delegations"] = [
            {
                "delegation_id": delegation_id,
                "turn_id": turn_id,
                "workspace_path": workspace_path,
            }
        ]
    conn = service._get_conn()
    conn.execute(
        """
        INSERT INTO chat_messages(
            message_id, session_id, turn_id, user_id, role, message_kind,
            content_text, payload_json, is_final, is_visible,
            created_at_ms, sequence_no
        ) VALUES (?, ?, ?, 'u1', ?, ?, 'private result', ?, 1, 1, ?, ?)
        """,
        (
            message_id,
            session_id,
            turn_id,
            role,
            "user_text" if role == "user" else "assistant_final",
            json.dumps(payload),
            created_at_ms,
            sequence_no,
        ),
    )
    if delegation_id is not None:
        conn.execute(
            """
            INSERT INTO chat_message_code_delegation_refs(
                message_id, session_id, delegation_id, turn_id,
                workspace_path, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                delegation_id,
                turn_id,
                workspace_path,
                created_at_ms,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO chat_code_delegation_artifacts(
                workspace_path, session_id, delegation_id, turn_id,
                created_at_ms
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                workspace_path,
                session_id,
                delegation_id,
                turn_id,
                created_at_ms,
            ),
        )
    conn.execute(
        """
        UPDATE chat_sessions
        SET message_count = message_count + 1,
            updated_at_ms = ?,
            last_message_at_ms = ?
        WHERE session_id = ?
        """,
        (created_at_ms, created_at_ms, session_id),
    )
    conn.commit()


def _artifact_rows(service: ChatReadService) -> tuple[int, int]:
    conn = service._get_conn()
    message_refs = conn.execute(
        "SELECT COUNT(*) FROM chat_message_code_delegation_refs"
    ).fetchone()
    registry = conn.execute(
        "SELECT COUNT(*) FROM chat_code_delegation_artifacts"
    ).fetchone()
    assert message_refs is not None
    assert registry is not None
    return int(message_refs[0]), int(registry[0])


def _registered_references(
    gc: _RecordingCodeAgentArtifactGC,
) -> list[CodeAgentDelegationReference]:
    return [reference for call in gc.calls for reference in call]


@pytest.mark.asyncio
async def test_message_write_persists_reference_and_registry_atomically(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    _seed_session(service, session_id="session-write")
    service.close()
    store = ChatStore(
        db_path=str(runtime_paths.chat_db_path),
        runtime_paths=runtime_paths,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reference_payload = {
        "code_agent_delegations": [
            {
                "delegation_id": "a" * 32,
                "turn_id": "turn-write",
                "workspace_path": str(workspace),
            }
        ]
    }
    message = ChatMessageRecord(
        message_id="message-write",
        session_id="session-write",
        turn_id="turn-write",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="done",
        payload_json=json.dumps(reference_payload),
        is_final=True,
        is_visible=True,
        created_at_ms=1,
        sequence_no=1,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )

    await store.append_message(message)

    with sqlite3.connect(runtime_paths.chat_db_path) as connection:
        assert connection.execute(
            """
            SELECT message_id, session_id, delegation_id, turn_id, workspace_path
            FROM chat_message_code_delegation_refs
            """
        ).fetchone() == (
            "message-write",
            "session-write",
            "a" * 32,
            "turn-write",
            str(workspace),
        )
        assert connection.execute(
            """
            SELECT session_id, delegation_id, turn_id, workspace_path
            FROM chat_code_delegation_artifacts
            """
        ).fetchone() == (
            "session-write",
            "a" * 32,
            "turn-write",
            str(workspace),
        )
        connection.execute(
            """
            CREATE TRIGGER fail_code_artifact_registry_insert
            BEFORE INSERT ON chat_code_delegation_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'injected registry failure');
            END
            """
        )
        connection.commit()

    failed_message = ChatMessageRecord(
        message_id="message-rollback",
        session_id="session-write",
        turn_id="turn-rollback",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="must roll back",
        payload_json=json.dumps(
            {
                "code_agent_delegations": [
                    {
                        "delegation_id": "b" * 32,
                        "turn_id": "turn-rollback",
                        "workspace_path": str(workspace),
                    }
                ]
            }
        ),
        is_final=True,
        is_visible=True,
        created_at_ms=2,
        sequence_no=2,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected registry failure"):
        await store.append_message(failed_message)

    with sqlite3.connect(runtime_paths.chat_db_path) as connection:
        assert connection.execute(
            "SELECT 1 FROM chat_messages WHERE message_id = 'message-rollback'"
        ).fetchone() is None
        assert connection.execute(
            """
            SELECT 1
            FROM chat_message_code_delegation_refs
            WHERE message_id = 'message-rollback'
            """
        ).fetchone() is None
        assert connection.execute(
            """
            SELECT 1
            FROM chat_code_delegation_artifacts
            WHERE delegation_id = ?
            """,
            ("b" * 32,),
        ).fetchone() is None


def test_exact_delete_redacts_then_recovers_after_restart(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_session(service, session_id="session-exact")
    _seed_turn(
        service,
        session_id="session-exact",
        turn_id="turn-exact",
    )
    _seed_message(
        service,
        session_id="session-exact",
        turn_id="turn-exact",
        message_id="message-exact",
        delegation_id="c" * 32,
        workspace_path=str(workspace),
    )
    failing_gc = _RecordingCodeAgentArtifactGC(failures=1)
    service._code_agent_artifact_gc = failing_gc

    with pytest.raises(ChatSurfaceCleanupPendingError):
        service.forget_message_artifacts(
            "u1",
            "session-exact",
            "message-exact",
        )

    redacted = service._get_conn().execute(
        """
        SELECT content_text, payload_json, is_visible
        FROM chat_messages
        WHERE message_id = 'message-exact'
        """
    ).fetchone()
    assert tuple(redacted) == ("", "{}", 0)
    assert _artifact_rows(service) == (1, 1)
    service.close()

    recovered = ChatReadService(runtime_paths=runtime_paths)
    recovered_gc = _RecordingCodeAgentArtifactGC()
    recovered._code_agent_artifact_gc = recovered_gc
    assert recovered.forget_message_artifacts(
        "u1",
        "session-exact",
        "message-exact",
    )

    assert recovered._get_conn().execute(
        "SELECT 1 FROM chat_messages WHERE message_id = 'message-exact'"
    ).fetchone() is None
    assert _artifact_rows(recovered) == (0, 0)
    assert [
        reference.delegation_id
        for reference in _registered_references(recovered_gc)
    ] == ["c" * 32]
    recovered.close()


def test_shared_artifact_is_deleted_only_after_last_visible_owner(
    tmp_path: Path,
) -> None:
    service, _ = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    delegation_id = "d" * 32
    _seed_session(service, session_id="session-shared")
    for index in (1, 2):
        _seed_turn(
            service,
            session_id="session-shared",
            turn_id=f"turn-{index}",
            created_at_ms=index,
        )
        _seed_message(
            service,
            session_id="session-shared",
            turn_id=f"turn-{index}",
            message_id=f"message-{index}",
            delegation_id=delegation_id,
            workspace_path=str(workspace),
            created_at_ms=index,
            sequence_no=index,
        )
    gc = _RecordingCodeAgentArtifactGC()
    service._code_agent_artifact_gc = gc

    assert service.forget_message_artifacts(
        "u1",
        "session-shared",
        "message-1",
    )

    assert _artifact_rows(service) == (1, 1)
    assert _registered_references(gc) == []
    assert service.forget_message_artifacts(
        "u1",
        "session-shared",
        "message-2",
    )
    assert _artifact_rows(service) == (0, 0)
    assert [
        reference.delegation_id for reference in _registered_references(gc)
    ] == [delegation_id]
    service.close()


def test_session_workspace_change_does_not_retarget_old_artifact_cleanup(
    tmp_path: Path,
) -> None:
    service, _ = _build_service(tmp_path)
    old_workspace = tmp_path / "workspace-old"
    new_workspace = tmp_path / "workspace-new"
    old_workspace.mkdir()
    new_workspace.mkdir()
    _seed_session(
        service,
        session_id="session-workspace",
        workspace_path=str(old_workspace),
    )
    _seed_turn(
        service,
        session_id="session-workspace",
        turn_id="turn-workspace",
    )
    _seed_message(
        service,
        session_id="session-workspace",
        turn_id="turn-workspace",
        message_id="message-workspace",
        delegation_id="e" * 32,
        workspace_path=str(old_workspace),
    )
    service.update_session_workspace(
        "u1",
        "session-workspace",
        str(new_workspace),
    )
    gc = _RecordingCodeAgentArtifactGC()
    service._code_agent_artifact_gc = gc

    service.delete_session("u1", "session-workspace")

    references = _registered_references(gc)
    assert [reference.workspace_path for reference in references] == [
        str(old_workspace)
    ]
    assert all(reference.workspace_path != str(new_workspace) for reference in references)
    assert _artifact_rows(service) == (0, 0)
    service.close()


def test_history_retry_preserves_messages_written_after_snapshot(
    tmp_path: Path,
) -> None:
    service, _ = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_session(service, session_id="session-history")
    _seed_turn(
        service,
        session_id="session-history",
        turn_id="turn-old",
    )
    _seed_message(
        service,
        session_id="session-history",
        turn_id="turn-old",
        message_id="message-old",
        role="user",
        delegation_id="f" * 32,
        workspace_path=str(workspace),
    )
    gc = _RecordingCodeAgentArtifactGC(failures=1)
    service._code_agent_artifact_gc = gc

    with pytest.raises(ChatSurfaceCleanupPendingError):
        service.clear_conversation_history_snapshot(
            "u1",
            "session-history",
            ["message-old"],
            ["turn-old"],
        )

    _seed_turn(
        service,
        session_id="session-history",
        turn_id="turn-new",
        created_at_ms=2,
    )
    _seed_message(
        service,
        session_id="session-history",
        turn_id="turn-new",
        message_id="message-new",
        role="user",
        created_at_ms=2,
        sequence_no=2,
    )
    service.clear_conversation_history_snapshot(
        "u1",
        "session-history",
        ["message-old"],
        ["turn-old"],
    )

    new_message = service._get_conn().execute(
        """
        SELECT content_text, is_visible
        FROM chat_messages
        WHERE message_id = 'message-new'
        """
    ).fetchone()
    assert tuple(new_message) == ("private result", 1)
    assert service._get_conn().execute(
        "SELECT 1 FROM chat_messages WHERE message_id = 'message-old'"
    ).fetchone() is None
    new_turn = service._get_conn().execute(
        "SELECT 1 FROM chat_turns WHERE turn_id = 'turn-new'"
    ).fetchone()
    assert tuple(new_turn) == (1,)
    assert service._get_conn().execute(
        "SELECT 1 FROM chat_turns WHERE turn_id = 'turn-old'"
    ).fetchone() is None
    assert _artifact_rows(service) == (0, 0)
    service.close()


def test_global_clear_recovers_after_crash_following_redaction(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_session(service, session_id="session-global")
    _seed_turn(
        service,
        session_id="session-global",
        turn_id="turn-global",
    )
    _seed_message(
        service,
        session_id="session-global",
        turn_id="turn-global",
        message_id="message-global",
        delegation_id="1" * 32,
        workspace_path=str(workspace),
    )
    service._clear_all_runtime_trace_rows = lambda: None  # type: ignore[method-assign]
    service._clear_all_chat_assets = lambda: None  # type: ignore[method-assign]
    service._code_agent_artifact_gc = _RecordingCodeAgentArtifactGC(
        failures=1
    )

    with pytest.raises(RuntimeError, match="injected private cleanup failure"):
        service.clear_all_sessions()

    redacted = service._get_conn().execute(
        """
        SELECT content_text, payload_json, is_visible
        FROM chat_messages
        WHERE message_id = 'message-global'
        """
    ).fetchone()
    assert tuple(redacted) == ("", "{}", 0)
    assert _artifact_rows(service) == (1, 1)
    intent = service._get_conn().execute(
        """
        SELECT session_count
        FROM chat_global_clear_intent
        WHERE intent_key = 'global'
        """
    ).fetchone()
    assert tuple(intent) == (1,)
    service.close()

    recovered = ChatReadService(runtime_paths=runtime_paths)
    recovered._clear_all_runtime_trace_rows = lambda: None  # type: ignore[method-assign]
    recovered._clear_all_chat_assets = lambda: None  # type: ignore[method-assign]
    recovered_gc = _RecordingCodeAgentArtifactGC()
    recovered._code_agent_artifact_gc = recovered_gc
    assert recovered.recover_interrupted_global_clear()
    assert _artifact_rows(recovered) == (0, 0)
    remaining_sessions = recovered._get_conn().execute(
        "SELECT COUNT(*) FROM chat_sessions"
    ).fetchone()
    assert tuple(remaining_sessions) == (0,)
    assert recovered.complete_global_clear()
    assert not recovered.complete_global_clear()
    assert [
        reference.delegation_id
        for reference in _registered_references(recovered_gc)
    ] == ["1" * 32]
    recovered.close()


def test_global_clear_deletes_artifact_owned_by_visible_message(
    tmp_path: Path,
) -> None:
    service, _ = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_session(service, session_id="session-global-visible")
    _seed_turn(
        service,
        session_id="session-global-visible",
        turn_id="turn-global-visible",
    )
    _seed_message(
        service,
        session_id="session-global-visible",
        turn_id="turn-global-visible",
        message_id="message-global-visible",
        delegation_id="5" * 32,
        workspace_path=str(workspace),
    )
    service._clear_all_runtime_trace_rows = lambda: None  # type: ignore[method-assign]
    service._clear_all_chat_assets = lambda: None  # type: ignore[method-assign]
    gc = _RecordingCodeAgentArtifactGC()
    service._code_agent_artifact_gc = gc

    assert service.clear_all_sessions() == 1

    assert [
        reference.delegation_id for reference in _registered_references(gc)
    ] == ["5" * 32]
    assert _artifact_rows(service) == (0, 0)
    assert service.complete_global_clear()
    service.close()


@pytest.mark.asyncio
async def test_orphan_registered_before_message_is_cleaned_by_turn(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_session(service, session_id="session-orphan-turn")
    _seed_turn(
        service,
        session_id="session-orphan-turn",
        turn_id="turn-orphan",
    )
    _seed_message(
        service,
        session_id="session-orphan-turn",
        turn_id="turn-orphan",
        message_id="message-user",
        role="user",
    )
    await ChatCodeDelegationArtifactRegistry(
        runtime_paths=runtime_paths
    ).register(
        session_id="session-orphan-turn",
        turn_id="turn-orphan",
        delegation_id="2" * 32,
        workspace_path=str(workspace),
    )
    gc = _RecordingCodeAgentArtifactGC()
    service._code_agent_artifact_gc = gc

    assert service.forget_message_artifacts(
        "u1",
        "session-orphan-turn",
        "message-user",
    )

    assert _artifact_rows(service) == (0, 0)
    assert [
        reference.delegation_id for reference in _registered_references(gc)
    ] == ["2" * 32]
    service.close()


@pytest.mark.asyncio
async def test_orphan_registered_before_message_is_cleaned_by_session(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_session(service, session_id="session-orphan")
    await ChatCodeDelegationArtifactRegistry(
        runtime_paths=runtime_paths
    ).register(
        session_id="session-orphan",
        turn_id="turn-never-written",
        delegation_id="3" * 32,
        workspace_path=str(workspace),
    )
    gc = _RecordingCodeAgentArtifactGC()
    service._code_agent_artifact_gc = gc

    service.delete_session("u1", "session-orphan")

    assert _artifact_rows(service) == (0, 0)
    assert [
        reference.delegation_id for reference in _registered_references(gc)
    ] == ["3" * 32]
    service.close()


@pytest.mark.asyncio
async def test_orphan_registered_before_message_is_cleaned_globally(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    await ChatCodeDelegationArtifactRegistry(
        runtime_paths=runtime_paths
    ).register(
        session_id="session-crashed-before-session",
        turn_id="turn-crashed",
        delegation_id="4" * 32,
        workspace_path=str(workspace),
    )
    service._clear_all_runtime_trace_rows = lambda: None  # type: ignore[method-assign]
    service._clear_all_chat_assets = lambda: None  # type: ignore[method-assign]
    gc = _RecordingCodeAgentArtifactGC()
    service._code_agent_artifact_gc = gc

    assert service.clear_all_sessions() == 0

    assert _artifact_rows(service) == (0, 0)
    assert [
        reference.delegation_id for reference in _registered_references(gc)
    ] == ["4" * 32]
    assert service.complete_global_clear()
    service.close()
