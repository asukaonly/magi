"""Tests for code_agent worktree management."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from magi.tools.code_agent.errors import NotAGitRepoError
from magi.tools.code_agent.workspace import (
    create_worktree,
    remove_worktree,
)


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, check=True)
    (path / "README.md").write_text("# repo\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def test_create_worktree_under_magi_sessions(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    delegation_id = "a" * 32
    wt = create_worktree(workspace_root=repo, session_id="s1", delegation_id=delegation_id)
    assert wt.is_dir()
    assert wt == repo / ".magi" / "sessions" / "s1" / "worktrees" / delegation_id
    assert (wt / "README.md").read_text() == "# repo\n"

    (wt / "README.md").write_text("work in progress\n")
    (wt / "new.py").write_text("untracked work\n")
    again = create_worktree(workspace_root=repo, session_id="s1", delegation_id=delegation_id)
    assert again == wt
    assert (again / "README.md").read_text() == "work in progress\n"
    assert (again / "new.py").read_text() == "untracked work\n"
    assert (repo / "README.md").read_text() == "# repo\n"
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert listing.splitlines().count(f"worktree {wt}") == 1


def test_remove_worktree_clears_directory(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    delegation_id = "c" * 32
    wt = create_worktree(workspace_root=repo, session_id="s1", delegation_id=delegation_id)
    remove_worktree(workspace_root=repo, worktree_path=wt)
    assert not wt.exists()
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    assert delegation_id not in listing


def test_create_worktree_rejects_non_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(NotAGitRepoError):
        create_worktree(
            workspace_root=plain, session_id="s1", delegation_id="d" * 32,
        )


def test_create_worktree_rejects_dirty_workspace(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    # Make uncommitted changes
    (repo / "dirty.txt").write_text("uncommitted")
    with pytest.raises(NotAGitRepoError) as exc_info:
        create_worktree(workspace_root=repo, session_id="s1", delegation_id="e" * 32)
    assert "uncommitted changes" in str(exc_info.value).lower()
    assert "dirty.txt" in str(exc_info.value)


@pytest.mark.parametrize(
    ("session_id", "delegation_id"),
    [
        ("../outside", "a" * 32),
        ("s1/child", "b" * 32),
        ("s1", "../outside"),
        ("s1", "z" * 32),
    ],
)
def test_create_worktree_rejects_unsafe_identity(
    tmp_path: Path,
    session_id: str,
    delegation_id: str,
) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    with pytest.raises(ValueError):
        create_worktree(
            workspace_root=repo,
            session_id=session_id,
            delegation_id=delegation_id,
        )


def test_create_worktree_rejects_symlink_workspace(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    alias = tmp_path / "repo-alias"
    alias.symlink_to(repo, target_is_directory=True)

    with pytest.raises(ValueError):
        create_worktree(
            workspace_root=alias,
            session_id="s1",
            delegation_id="a" * 32,
        )


def test_create_worktree_rejects_symlinked_artifact_scope(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".magi").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        create_worktree(
            workspace_root=repo,
            session_id="s1",
            delegation_id="a" * 32,
        )


def test_create_worktree_rejects_symlinked_worktree_leaf(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    worktrees_root = repo / ".magi" / "sessions" / "s1" / "worktrees"
    worktrees_root.mkdir(parents=True)
    (worktrees_root / ("a" * 32)).symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(ValueError):
        create_worktree(
            workspace_root=repo,
            session_id="s1",
            delegation_id="a" * 32,
        )


def test_remove_worktree_rejects_path_outside_scope(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError):
        remove_worktree(
            workspace_root=repo,
            worktree_path=outside,
        )
