"""Tests for code_agent diff collector."""
from __future__ import annotations

import subprocess
from pathlib import Path

from magi.tools.code_agent.contracts import DiffSnapshot
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


def test_clean_repo_returns_empty_diff(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    snap = collect_diff(repo)
    assert isinstance(snap, DiffSnapshot)
    assert snap.stats.files_changed == 0
    assert snap.unified_diff == ""
    assert snap.files_changed == []
    assert snap.status_porcelain == ""


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


def test_collect_diff_non_repo_returns_empty(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    snap = collect_diff(plain)
    assert isinstance(snap, DiffSnapshot)
    assert snap.stats.files_changed == 0
