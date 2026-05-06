"""Tests for code_agent worktree management."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from magi.tools.code_agent.errors import NotAGitRepoError
from magi.tools.code_agent.workspace import (
    assert_git_repo,
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


def test_assert_git_repo_passes_on_repo(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    assert_git_repo(repo)


def test_assert_git_repo_raises_on_non_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(NotAGitRepoError):
        assert_git_repo(plain)


def test_create_worktree_under_magi_sessions(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    delegation_id = "a" * 32
    wt = create_worktree(workspace_root=repo, session_id="s1", delegation_id=delegation_id)
    assert wt.is_dir()
    assert wt == repo / ".magi" / "sessions" / "s1" / "worktrees" / delegation_id
    assert (wt / "README.md").read_text() == "# repo\n"


def test_create_worktree_idempotent(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "repo")
    delegation_id = "b" * 32
    wt1 = create_worktree(workspace_root=repo, session_id="s1", delegation_id=delegation_id)
    wt2 = create_worktree(workspace_root=repo, session_id="s1", delegation_id=delegation_id)
    assert wt1 == wt2
    assert wt1.is_dir()


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
