"""Tests for apply / discard helpers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from magi.tools.code_agent.apply_diff import (
    ApplyOutcome,
    apply_delegation,
    discard_delegation,
)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, check=True)
    (path / "src").mkdir()
    (path / "src" / "net.py").write_text("def connect():\n    return 1\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _stage_delegation(repo: Path, did: str, *, patch_text: str, result_payload: dict) -> Path:
    delegation_dir = repo / ".magi" / "sessions" / "s1" / "delegations" / did
    delegation_dir.mkdir(parents=True, exist_ok=True)
    (delegation_dir / "changes.patch").write_text(patch_text)
    (delegation_dir / "result.json").write_text(json.dumps(result_payload))
    return delegation_dir


_SAMPLE_PATCH = (
    "diff --git a/src/net.py b/src/net.py\n"
    "--- a/src/net.py\n"
    "+++ b/src/net.py\n"
    "@@ -1,2 +1,3 @@\n"
    "-def connect():\n"
    "-    return 1\n"
    "+def connect(max_retries=3):\n"
    "+    \"\"\"Connect with retry.\"\"\"\n"
    "+    return 1\n"
)


def test_apply_delegation_applies_patch_to_workspace(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "a" * 32
    _stage_delegation(repo, did, patch_text=_SAMPLE_PATCH, result_payload={
        "delegation_id": did, "success": True,
    })
    outcome = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert outcome.applied is True
    assert "src/net.py" in outcome.files_applied
    contents = (repo / "src" / "net.py").read_text()
    assert "max_retries" in contents


def test_apply_delegation_records_edit(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "b" * 32
    _stage_delegation(repo, did, patch_text=_SAMPLE_PATCH, result_payload={
        "delegation_id": did, "success": True,
    })
    apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    edits_path = repo / ".magi" / "sessions" / "s1" / "edits.jsonl"
    assert edits_path.is_file()
    lines = edits_path.read_text().splitlines()
    matching = [l for l in lines if "src/net.py" in l]
    assert matching, "expected edit record for src/net.py"


def test_apply_delegation_idempotent(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "c" * 32
    _stage_delegation(repo, did, patch_text=_SAMPLE_PATCH, result_payload={
        "delegation_id": did, "success": True,
    })
    first = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    second = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert first.applied is True
    assert second.applied is True
    assert (second.error or "").lower().startswith("already")


def test_apply_delegation_missing_directory(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    outcome = apply_delegation(
        workspace_root=repo, session_id="s1", delegation_id="d" * 32,
    )
    assert outcome.applied is False
    assert "not found" in (outcome.error or "").lower()


def test_apply_delegation_empty_patch(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "e" * 32
    _stage_delegation(repo, did, patch_text="", result_payload={"delegation_id": did})
    outcome = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert outcome.applied is False
    assert "no diff" in (outcome.error or "").lower()


def test_apply_delegation_conflict_returns_rejects(tmp_path: Path) -> None:
    """If the file's current state diverges, git apply --3way fails."""
    repo = _make_repo(tmp_path / "repo")
    did = "f" * 32
    # Mutate target file so the patch's old content no longer matches.
    (repo / "src" / "net.py").write_text("def connect():\n    return 999\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "drift"], cwd=repo, check=True)
    _stage_delegation(repo, did, patch_text=_SAMPLE_PATCH, result_payload={
        "delegation_id": did,
    })
    outcome = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert outcome.applied is False


def test_discard_delegation_removes_worktree_and_stamps(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "g" * 32
    delegation_dir = _stage_delegation(repo, did, patch_text=_SAMPLE_PATCH, result_payload={
        "delegation_id": did, "success": True,
    })
    # No worktree exists; discard should still stamp result.json and not raise.
    discard_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    payload = json.loads((delegation_dir / "result.json").read_text())
    assert payload.get("discarded_at")


def test_discard_delegation_when_directory_missing_is_noop(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    discard_delegation(workspace_root=repo, session_id="s1", delegation_id="z" * 32)
