from __future__ import annotations

from pathlib import Path

import pytest

from _shared.db_schema import apply_chain_schema
from magi.chat.read_service import ChatReadService
from magi.core.code_agent_artifacts import WorkspaceSessionArtifactReference
from magi.utils.runtime import RuntimePaths


class _FailingWorkspaceSessionGC:
    def __init__(self) -> None:
        self.calls: list[list[WorkspaceSessionArtifactReference]] = []

    def delete_references(
        self,
        references: list[WorkspaceSessionArtifactReference],
    ) -> int:
        self.calls.append(list(references))
        raise RuntimeError("injected workspace session cleanup failure")


def _build_service(tmp_path: Path) -> tuple[ChatReadService, RuntimePaths]:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    apply_chain_schema("chat", runtime_paths.chat_db_path)
    service = ChatReadService(runtime_paths=runtime_paths)
    service._clear_all_runtime_trace_rows = lambda: None  # type: ignore[method-assign]
    service._clear_all_chat_assets = lambda: None  # type: ignore[method-assign]
    return service, runtime_paths


def _seed_session(service: ChatReadService, *, session_id: str, workspace: Path) -> None:
    service._get_conn().execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, summary, workspace_path,
            created_at_ms, updated_at_ms, message_count
        ) VALUES (?, 'u1', 'Private chat', 'Private summary', ?, 1, 1, 0)
        """,
        (session_id, str(workspace)),
    )
    service._get_conn().commit()


def test_global_clear_retries_workspace_session_cache_after_restart(
    tmp_path: Path,
) -> None:
    service, runtime_paths = _build_service(tmp_path)
    workspace = tmp_path / "workspace"
    target = workspace / ".magi" / "sessions" / "session-a"
    sibling = workspace / ".magi" / "sessions" / "session-b"
    snapshots = target / "snapshots"
    snapshots.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (target / "reads.jsonl").write_text('{"path":"private.txt"}\n')
    (target / "edits.jsonl").write_text('{"path":"private.txt"}\n')
    (target / "todo.json").write_text('{"items":["private"]}')
    (snapshots / "private.bin").write_bytes(b"private file bytes")
    (sibling / "reads.jsonl").write_text('{"path":"keep.txt"}\n')
    workspace_metadata = workspace / ".magi" / "workspace.json"
    workspace_metadata.write_text('{"schema_version":1}')
    _seed_session(service, session_id="session-a", workspace=workspace)
    failing_gc = _FailingWorkspaceSessionGC()
    service._workspace_session_artifact_gc = failing_gc

    with pytest.raises(RuntimeError, match="workspace session cleanup failure"):
        service.clear_all_sessions()

    assert failing_gc.calls == [
        [
            WorkspaceSessionArtifactReference(
                workspace_path=str(workspace),
                session_id="session-a",
            )
        ]
    ]
    redacted = service._get_conn().execute(
        """
        SELECT title, summary, workspace_path, deleted_at_ms
        FROM chat_sessions
        WHERE session_id = 'session-a'
        """
    ).fetchone()
    assert tuple(redacted[:3]) == ("", "", None)
    assert redacted[3] is not None
    cleanup = service._get_conn().execute(
        """
        SELECT workspace_path, session_id
        FROM chat_workspace_session_cleanup
        """
    ).fetchall()
    assert [tuple(row) for row in cleanup] == [(str(workspace), "session-a")]
    assert target.exists()
    service.close()

    recovered = ChatReadService(runtime_paths=runtime_paths)
    recovered._clear_all_runtime_trace_rows = lambda: None  # type: ignore[method-assign]
    recovered._clear_all_chat_assets = lambda: None  # type: ignore[method-assign]

    assert recovered.recover_interrupted_global_clear()
    assert not target.exists()
    assert (sibling / "reads.jsonl").exists()
    assert workspace_metadata.exists()
    assert recovered._get_conn().execute(
        "SELECT COUNT(*) FROM chat_workspace_session_cleanup"
    ).fetchone()[0] == 0
    assert recovered.complete_global_clear()
    recovered.close()
