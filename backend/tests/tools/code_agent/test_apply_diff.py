"""Tests for apply / discard helpers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from magi.tools.code_agent.apply_diff import (
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
    matching = [line for line in lines if "src/net.py" in line]
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
    contents_before = (repo / "src" / "net.py").read_bytes()
    outcome = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert outcome.applied is False
    assert (repo / "src" / "net.py").read_bytes() == contents_before
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/net.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""


def test_discard_delegation_removes_worktree_and_stamps(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "1" * 32
    delegation_dir = _stage_delegation(repo, did, patch_text=_SAMPLE_PATCH, result_payload={
        "delegation_id": did, "success": True,
    })
    # No worktree exists; discard should still stamp result.json and not raise.
    discard_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    payload = json.loads((delegation_dir / "result.json").read_text())
    assert payload.get("discarded_at")


def test_discard_delegation_when_directory_missing_is_noop(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    discard_delegation(workspace_root=repo, session_id="s1", delegation_id="0" * 32)


@pytest.mark.parametrize(
    ("session_id", "delegation_id"),
    [
        ("../outside", "a" * 32),
        ("s1/child", "b" * 32),
        ("s1", "../outside"),
        ("s1", "z" * 32),
    ],
)
def test_apply_delegation_rejects_unsafe_identity(
    tmp_path: Path,
    session_id: str,
    delegation_id: str,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    with pytest.raises(ValueError):
        apply_delegation(
            workspace_root=repo,
            session_id=session_id,
            delegation_id=delegation_id,
        )


def test_apply_delegation_rejects_symlinked_delegation_scope(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "2" * 32
    outside = tmp_path / "outside"
    outside.mkdir()
    delegations_root = repo / ".magi" / "sessions" / "s1" / "delegations"
    delegations_root.mkdir(parents=True)
    (delegations_root / did).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        apply_delegation(
            workspace_root=repo,
            session_id="s1",
            delegation_id=did,
        )


def test_apply_delegation_rejects_symlinked_patch_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "3" * 32
    delegation_dir = _stage_delegation(
        repo,
        did,
        patch_text=_SAMPLE_PATCH,
        result_payload={"delegation_id": did},
    )
    outside_patch = tmp_path / "outside.patch"
    outside_patch.write_text(_SAMPLE_PATCH)
    (delegation_dir / "changes.patch").unlink()
    (delegation_dir / "changes.patch").symlink_to(outside_patch)

    with pytest.raises(ValueError):
        apply_delegation(
            workspace_root=repo,
            session_id="s1",
            delegation_id=did,
        )


def test_apply_delegation_rejects_patch_path_escape(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "4" * 32
    escaped_patch = (
        "diff --git a/../outside.txt b/../outside.txt\n"
        "--- a/../outside.txt\n"
        "+++ b/../outside.txt\n"
        "@@ -0,0 +1 @@\n"
        "+unsafe\n"
    )
    _stage_delegation(
        repo,
        did,
        patch_text=escaped_patch,
        result_payload={"delegation_id": did},
    )

    with pytest.raises(ValueError):
        apply_delegation(
            workspace_root=repo,
            session_id="s1",
            delegation_id=did,
        )


def test_apply_delegation_rolls_back_when_result_stamp_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "5" * 32
    _stage_delegation(
        repo,
        did,
        patch_text=_SAMPLE_PATCH,
        result_payload={"delegation_id": did},
    )
    contents_before = (repo / "src" / "net.py").read_bytes()

    def fail_result_write(_result_path: Path, _payload: dict) -> None:
        raise OSError("injected result write failure")

    monkeypatch.setattr(
        "magi.tools.code_agent.apply_diff._write_result",
        fail_result_write,
    )

    with pytest.raises(OSError, match="injected result write failure"):
        apply_delegation(
            workspace_root=repo,
            session_id="s1",
            delegation_id=did,
        )
    assert (repo / "src" / "net.py").read_bytes() == contents_before
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/net.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""


def test_apply_delegation_rolls_back_when_edit_ledger_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "a1" * 16
    delegation_dir = _stage_delegation(
        repo,
        did,
        patch_text=_SAMPLE_PATCH,
        result_payload={"delegation_id": did, "success": True},
    )
    contents_before = (repo / "src" / "net.py").read_bytes()
    result_before = (delegation_dir / "result.json").read_bytes()

    def fail_edit_ledger_write(*_args, **_kwargs) -> None:
        raise OSError("injected edit ledger failure")

    monkeypatch.setattr(
        "magi_plugin_sdk.workspace_cache.session.append_jsonl_many",
        fail_edit_ledger_write,
    )

    outcome = apply_delegation(
        workspace_root=repo,
        session_id="s1",
        delegation_id=did,
    )

    assert outcome.applied is False
    assert "rollback history" in (outcome.error or "")
    assert (repo / "src" / "net.py").read_bytes() == contents_before
    assert (delegation_dir / "result.json").read_bytes() == result_before
    assert not (
        repo / ".magi" / "sessions" / "s1" / "edits.jsonl"
    ).exists()


def test_apply_delegation_rejects_symlinked_patch_target(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "6" * 32
    (repo / "src" / "alias.py").symlink_to(repo / "src" / "net.py")
    patch = (
        "diff --git a/src/alias.py b/src/alias.py\n"
        "--- a/src/alias.py\n"
        "+++ b/src/alias.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def connect():\n"
        "+def connect(value=1):\n"
        "     return 1\n"
    )
    _stage_delegation(
        repo,
        did,
        patch_text=patch,
        result_payload={"delegation_id": did},
    )

    with pytest.raises(ValueError, match="symbolic-link"):
        apply_delegation(
            workspace_root=repo,
            session_id="s1",
            delegation_id=did,
        )


def test_apply_delegation_requires_valid_result_before_editing(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "7" * 32
    delegation_dir = _stage_delegation(
        repo,
        did,
        patch_text=_SAMPLE_PATCH,
        result_payload={"delegation_id": did},
    )
    (delegation_dir / "result.json").write_text("not-json")

    outcome = apply_delegation(
        workspace_root=repo,
        session_id="s1",
        delegation_id=did,
    )

    assert outcome.applied is False
    assert "result" in (outcome.error or "").lower()
    assert "max_retries" not in (repo / "src" / "net.py").read_text()


def test_apply_delegation_tracks_both_sides_of_rename(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "8" * 32
    rename_patch = (
        "diff --git a/src/net.py b/src/client.py\n"
        "similarity index 100%\n"
        "rename from src/net.py\n"
        "rename to src/client.py\n"
    )
    _stage_delegation(
        repo,
        did,
        patch_text=rename_patch,
        result_payload={"delegation_id": did},
    )

    outcome = apply_delegation(
        workspace_root=repo,
        session_id="s1",
        delegation_id=did,
    )

    assert outcome.applied is True
    assert outcome.files_applied == ["src/net.py", "src/client.py"]
    assert not (repo / "src" / "net.py").exists()
    assert (repo / "src" / "client.py").is_file()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/net.py", "src/client.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.startswith(" D src/net.py\n?? src/client.py")


def test_apply_delegation_rejects_special_file_mode(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    did = "9" * 32
    symlink_patch = (
        "diff --git a/src/link b/src/link\n"
        "new file mode 120000\n"
        "--- /dev/null\n"
        "+++ b/src/link\n"
        "@@ -0,0 +1 @@\n"
        "+../../outside\n"
        "\\ No newline at end of file\n"
    )
    _stage_delegation(
        repo,
        did,
        patch_text=symlink_patch,
        result_payload={"delegation_id": did},
    )

    outcome = apply_delegation(
        workspace_root=repo,
        session_id="s1",
        delegation_id=did,
    )

    assert outcome.applied is False
    assert "unsupported special file" in (outcome.error or "")
    assert not (repo / "src" / "link").exists()
