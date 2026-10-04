"""Tests for code_agent diff collector."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from magi.tools.code_agent.diff_collector import collect_diff


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, check=True)
    (path / "a.txt").write_text("v1\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


@pytest.mark.parametrize("is_repo", [False, True])
def test_collector_returns_empty_snapshot_for_clean_or_non_repository(tmp_path, is_repo):
    workspace = tmp_path / "workspace"
    if is_repo:
        _make_repo(workspace)
    else:
        workspace.mkdir()
    assert collect_diff(workspace).model_dump() == {
        "stats": {"files_changed": 0, "additions": 0, "deletions": 0},
        "files_changed": [],
        "unified_diff": "",
        "status_porcelain": "",
    }


def test_modified_file_appears_in_diff(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    (repo / "a.txt").write_text("v2\n")
    snap = collect_diff(repo)
    assert snap.stats.files_changed == 1
    assert "a.txt" in snap.files_changed
    assert "-v1" in snap.unified_diff
    assert "+v2" in snap.unified_diff
    assert snap.stats.additions >= 1
    assert snap.stats.deletions >= 1


def test_new_file_appears_in_diff_and_status(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    (repo / "b.txt").write_text("new\n")
    snap = collect_diff(repo)
    assert "b.txt" in snap.status_porcelain
    assert "?? b.txt" in snap.status_porcelain
    assert snap.files_changed == ["b.txt"]
    assert "new file mode" in snap.unified_diff
    assert "+new" in snap.unified_diff
