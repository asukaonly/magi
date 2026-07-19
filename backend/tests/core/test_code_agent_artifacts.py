from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from magi.core.code_agent_artifacts import (
    CodeAgentArtifactDeletionError,
    CodeAgentArtifactGC,
    CodeAgentDelegationReference,
)


def _run_git(workspace: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_workspace(
    tmp_path: Path,
    *,
    session_id: str = "session-safe",
    delegation_id: str = "a" * 32,
) -> tuple[Path, CodeAgentDelegationReference, Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _run_git(workspace, "init")
    _run_git(workspace, "config", "user.email", "tests@example.invalid")
    _run_git(workspace, "config", "user.name", "Magi Tests")
    applied_file = workspace / "applied.txt"
    applied_file.write_text("applied result\n", encoding="utf-8")
    _run_git(workspace, "add", "applied.txt")
    _run_git(workspace, "commit", "-m", "initial")

    worktree = (
        workspace
        / ".magi"
        / "sessions"
        / session_id
        / "worktrees"
        / delegation_id
    )
    worktree.parent.mkdir(parents=True)
    _run_git(
        workspace,
        "worktree",
        "add",
        "-b",
        f"magi/delegation/{delegation_id}",
        str(worktree),
        "HEAD",
    )
    log_dir = (
        workspace
        / ".magi"
        / "sessions"
        / session_id
        / "delegations"
        / delegation_id
    )
    log_dir.mkdir(parents=True)
    (log_dir / "result.json").write_text('{"private": true}\n', encoding="utf-8")
    applied_file.write_text(
        "applied result from delegation\n",
        encoding="utf-8",
    )
    reference = CodeAgentDelegationReference(
        session_id=session_id,
        delegation_id=delegation_id,
        turn_id="turn-safe",
        workspace_path=str(workspace),
    )
    return workspace, reference, worktree, log_dir


def test_delete_reference_is_strict_idempotent_and_preserves_applied_files(
    tmp_path: Path,
) -> None:
    workspace, reference, worktree, log_dir = _build_workspace(tmp_path)
    applied_file = workspace / "applied.txt"

    assert CodeAgentArtifactGC().delete_references([reference, reference]) == 1

    assert not worktree.exists()
    assert not log_dir.exists()
    assert (
        applied_file.read_text(encoding="utf-8")
        == "applied result from delegation\n"
    )
    diff = subprocess.run(
        ["git", "diff", "--exit-code", "--", "applied.txt"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    assert diff.returncode == 1
    branch = subprocess.run(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/magi/delegation/{reference.delegation_id}",
        ],
        cwd=workspace,
        check=False,
    )
    assert branch.returncode == 1
    assert CodeAgentArtifactGC().delete_references([reference]) == 0
    assert (
        applied_file.read_text(encoding="utf-8")
        == "applied result from delegation\n"
    )


def test_delete_reference_rejects_symlinked_workspace_without_touching_target(
    tmp_path: Path,
) -> None:
    workspace, reference, worktree, log_dir = _build_workspace(tmp_path)
    workspace_link = tmp_path / "workspace-link"
    try:
        workspace_link.symlink_to(workspace, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not available on this platform")

    unsafe_reference = CodeAgentDelegationReference(
        session_id=reference.session_id,
        delegation_id=reference.delegation_id,
        turn_id=reference.turn_id,
        workspace_path=str(workspace_link),
    )
    with pytest.raises(CodeAgentArtifactDeletionError):
        CodeAgentArtifactGC().delete_references([unsafe_reference])

    assert worktree.is_dir()
    assert log_dir.is_dir()
    assert (workspace / "applied.txt").is_file()


def test_delete_reference_rejects_broken_workspace_symlink(
    tmp_path: Path,
) -> None:
    workspace_link = tmp_path / "broken-workspace"
    try:
        workspace_link.symlink_to(
            tmp_path / "missing-workspace",
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("Symlinks are not available on this platform")
    reference = CodeAgentDelegationReference(
        session_id="session-safe",
        delegation_id="b" * 32,
        turn_id="turn-safe",
        workspace_path=str(workspace_link),
    )

    with pytest.raises(CodeAgentArtifactDeletionError):
        CodeAgentArtifactGC().delete_references([reference])

    assert workspace_link.is_symlink()


def test_delete_reference_rejects_symlinked_artifact_scope_without_touching_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _run_git(workspace, "init")
    outside = tmp_path / "outside"
    outside.mkdir()
    private_file = outside / "private.txt"
    private_file.write_text("keep", encoding="utf-8")
    session_root = workspace / ".magi" / "sessions" / "session-safe"
    session_root.mkdir(parents=True)
    try:
        (session_root / "delegations").symlink_to(
            outside,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("Symlinks are not available on this platform")
    reference = CodeAgentDelegationReference(
        session_id="session-safe",
        delegation_id="b" * 32,
        turn_id="turn-safe",
        workspace_path=str(workspace),
    )

    with pytest.raises(CodeAgentArtifactDeletionError):
        CodeAgentArtifactGC().delete_references([reference])

    assert private_file.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("session_id", "workspace_suffix"),
    [
        ("../session", ""),
        ("session-safe", "/../workspace"),
    ],
)
def test_delete_reference_rejects_dangerous_identity_or_workspace_spelling(
    tmp_path: Path,
    session_id: str,
    workspace_suffix: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _run_git(workspace, "init")
    reference = CodeAgentDelegationReference(
        session_id=session_id,
        delegation_id="c" * 32,
        turn_id="turn-safe",
        workspace_path=f"{workspace}{workspace_suffix}",
    )

    with pytest.raises((CodeAgentArtifactDeletionError, ValueError)):
        CodeAgentArtifactGC().delete_references([reference])


def test_delete_reference_reports_failed_git_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, reference, _, log_dir = _build_workspace(tmp_path)
    original_run_git = CodeAgentArtifactGC._run_git

    def fail_prune(
        workspace_root: Path,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        if arguments == ("worktree", "prune"):
            return subprocess.CompletedProcess(
                ["git", *arguments],
                returncode=2,
                stdout="",
                stderr="injected prune failure",
            )
        return original_run_git(workspace_root, *arguments)

    monkeypatch.setattr(CodeAgentArtifactGC, "_run_git", staticmethod(fail_prune))

    with pytest.raises(
        CodeAgentArtifactDeletionError,
        match="worktree metadata",
    ):
        CodeAgentArtifactGC().delete_references([reference])

    assert log_dir.is_dir()
