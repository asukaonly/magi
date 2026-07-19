"""Per-delegation git worktree CRUD.

Each delegation gets a fresh worktree at
``<workspace_root>/.magi/sessions/<sid>/worktrees/<delegation_id>``.
The worktree is a checkout of the workspace's HEAD on a fresh branch, so the
external CLI mutates an isolated tree and we can grab a clean diff afterwards.

Only git repositories are supported in this iteration. Non-repo workspaces
raise ``NotAGitRepoError``.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ...core.code_agent_artifacts import (
    CodeAgentArtifactLocator,
    CodeAgentArtifactPathError,
    resolve_code_agent_workspace_root,
)
from .errors import NotAGitRepoError


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd, capture_output=True, text=True, check=False,
    )


def assert_git_repo(workspace_root: Path) -> None:
    try:
        workspace_root = resolve_code_agent_workspace_root(workspace_root)
    except ValueError as exc:
        raise NotAGitRepoError(str(exc)) from exc
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=workspace_root)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise NotAGitRepoError(f"not a git repository: {workspace_root}")


def create_worktree(
    *,
    workspace_root: Path,
    session_id: str,
    delegation_id: str,
) -> Path:
    paths = CodeAgentArtifactLocator.resolve(
        workspace_root=workspace_root,
        session_id=session_id,
        delegation_id=delegation_id,
    )
    workspace_root = paths.workspace_root
    assert_git_repo(workspace_root)
    # Check for uncommitted changes - delegation requires clean working directory
    status = _run_git(["status", "--porcelain"], cwd=workspace_root)
    if status.returncode != 0:
        raise NotAGitRepoError(
            f"git status failed: {status.stderr.strip() or status.stdout.strip()}"
        )
    if status.stdout.strip():
        changed_files: list[str] = []
        for line in status.stdout.strip().splitlines():
            parts = line.split(maxsplit=1)
            changed_path = parts[1] if len(parts) > 1 else line.strip()
            if (
                changed_path
                and changed_path != ".magi"
                and not changed_path.startswith(".magi/")
            ):
                changed_files.append(changed_path)
        if changed_files:
            files_list = ", ".join(changed_files[:5])
            if len(changed_files) > 5:
                files_list += ", ..."
            raise NotAGitRepoError(
                f"Workspace has uncommitted changes ({files_list}). "
                f"Commit or stash them before delegating, or the worktree diff won't apply cleanly."
            )
    paths.ensure_worktrees_root()
    target = paths.worktree_dir
    existing_target = paths.existing_worktree_dir()
    if existing_target is not None:
        git_marker = existing_target / ".git"
        if git_marker.is_symlink():
            raise CodeAgentArtifactPathError(
                "worktree git marker must not be a symbolic link"
            )
        if git_marker.is_file():
            top_level = _run_git(
                ["rev-parse", "--show-toplevel"],
                cwd=existing_target,
            )
            if (
                top_level.returncode == 0
                and Path(top_level.stdout.strip()).resolve() == existing_target
            ):
                return target
    branch_name = f"magi/delegation/{paths.delegation_id}"
    head = _run_git(["rev-parse", "HEAD"], cwd=workspace_root)
    if head.returncode != 0:
        raise NotAGitRepoError(f"git rev-parse HEAD failed: {head.stderr.strip()}")
    sha = head.stdout.strip()
    add = _run_git(
        ["worktree", "add", "-b", branch_name, str(target), sha],
        cwd=workspace_root,
    )
    if add.returncode != 0:
        raise NotAGitRepoError(
            f"git worktree add failed: {add.stderr.strip() or add.stdout.strip()}"
        )
    return target


def remove_worktree(*, workspace_root: Path, worktree_path: Path) -> None:
    workspace_root = resolve_code_agent_workspace_root(workspace_root)
    raw_worktree_path = Path(worktree_path).expanduser()
    if not raw_worktree_path.is_absolute():
        raise ValueError("worktree path must be absolute")
    try:
        relative_parts = raw_worktree_path.absolute().relative_to(workspace_root).parts
    except ValueError as exc:
        raise ValueError("worktree path is outside the workspace") from exc
    if (
        len(relative_parts) != 5
        or relative_parts[0] != ".magi"
        or relative_parts[1] != "sessions"
        or relative_parts[3] != "worktrees"
    ):
        raise ValueError("worktree path does not match a delegation scope")
    paths = CodeAgentArtifactLocator.resolve(
        workspace_root=workspace_root,
        session_id=relative_parts[2],
        delegation_id=relative_parts[4],
    )
    worktree_path = paths.validate_worktree_path(raw_worktree_path)
    removal = _run_git(
        ["worktree", "remove", "--force", str(worktree_path)],
        cwd=workspace_root,
    )
    if removal.returncode != 0:
        raise RuntimeError(
            "git worktree removal failed: "
            f"{removal.stderr.strip() or removal.stdout.strip()}"
        )
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
    if worktree_path.exists() or worktree_path.is_symlink():
        raise RuntimeError("worktree directory could not be removed")
    prune = _run_git(["worktree", "prune"], cwd=workspace_root)
    if prune.returncode != 0:
        raise RuntimeError(
            "git worktree metadata cleanup failed: "
            f"{prune.stderr.strip() or prune.stdout.strip()}"
        )


__all__ = ["assert_git_repo", "create_worktree", "remove_worktree"]
