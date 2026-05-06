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

from .errors import NotAGitRepoError


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd, capture_output=True, text=True, check=False,
    )


def assert_git_repo(workspace_root: Path) -> None:
    if not workspace_root.is_dir():
        raise NotAGitRepoError(f"workspace does not exist: {workspace_root}")
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=workspace_root)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise NotAGitRepoError(f"not a git repository: {workspace_root}")


def _worktree_path(workspace_root: Path, session_id: str, delegation_id: str) -> Path:
    return workspace_root / ".magi" / "sessions" / session_id / "worktrees" / delegation_id


def create_worktree(
    *,
    workspace_root: Path,
    session_id: str,
    delegation_id: str,
) -> Path:
    workspace_root = Path(workspace_root).resolve()
    assert_git_repo(workspace_root)
    target = _worktree_path(workspace_root, session_id, delegation_id)
    if target.is_dir() and (target / ".git").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    branch_name = f"magi/delegation/{delegation_id}"
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
    workspace_root = Path(workspace_root).resolve()
    worktree_path = Path(worktree_path).resolve()
    _run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=workspace_root)
    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)


__all__ = ["assert_git_repo", "create_worktree", "remove_worktree"]
