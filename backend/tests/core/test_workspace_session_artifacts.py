from pathlib import Path

import pytest

from magi.core.code_agent_artifacts import (
    CodeAgentArtifactDeletionError,
    WorkspaceSessionArtifactGC,
    WorkspaceSessionArtifactReference,
)


def test_workspace_session_artifact_gc_removes_only_exact_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / ".magi" / "sessions" / "session-a"
    sibling = workspace / ".magi" / "sessions" / "session-b"
    target_snapshots = target / "snapshots"
    target_snapshots.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (target / "reads.jsonl").write_text('{"path":"private.txt"}\n')
    (target / "edits.jsonl").write_text('{"path":"private.txt"}\n')
    (target / "todo.json").write_text('{"items":["private"]}')
    (target_snapshots / "private.bin").write_bytes(b"private file bytes")
    (sibling / "reads.jsonl").write_text('{"path":"keep.txt"}\n')
    workspace_metadata = workspace / ".magi" / "workspace.json"
    workspace_metadata.write_text('{"schema_version":1}')

    gc = WorkspaceSessionArtifactGC()
    reference = WorkspaceSessionArtifactReference(
        workspace_path=str(workspace),
        session_id="session-a",
    )

    assert gc.delete_references([reference, reference]) == 1
    assert not target.exists()
    assert (sibling / "reads.jsonl").exists()
    assert workspace_metadata.exists()
    assert gc.delete_references([reference]) == 0


def test_workspace_session_artifact_gc_rejects_symlinked_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sessions = workspace / ".magi" / "sessions"
    sessions.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep")
    (sessions / "session-a").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CodeAgentArtifactDeletionError, match="not safe"):
        WorkspaceSessionArtifactGC().delete_references(
            [
                WorkspaceSessionArtifactReference(
                    workspace_path=str(workspace),
                    session_id="session-a",
                )
            ]
        )

    assert sentinel.read_text() == "keep"
    assert (sessions / "session-a").is_symlink()
