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


def test_apply_patch_persists_restorable_edit_history_once(tmp_path):
    import hashlib
    from magi_plugin_sdk.workspace_cache import SnapshotRef, resolve_session_cache

    repo = _make_repo(tmp_path / "repo")
    target = repo / "src/net.py"
    before = target.read_bytes()
    did = "a" * 32
    delegation = _stage_delegation(
        repo, did, patch_text=_SAMPLE_PATCH, result_payload={"delegation_id": did, "success": True}
    )
    outcome = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    expected = b'def connect(max_retries=3):\n    """Connect with retry."""\n    return 1\n'
    assert outcome.applied is True
    assert outcome.files_applied == ["src/net.py"]
    assert target.read_bytes() == expected
    cache = resolve_session_cache(repo, "s1")
    records = list(cache.iter_edits())
    assert len(records) == 1
    record = records[0]
    assert (record.path, record.op) == ("src/net.py", "replace")
    assert record.sha256_before == record.snapshot_ref == hashlib.sha256(before).hexdigest()
    assert record.sha256_after == hashlib.sha256(expected).hexdigest()
    assert cache.read_snapshot(SnapshotRef(sha256=record.snapshot_ref)) == before
    persisted = json.loads((delegation / "result.json").read_text())
    assert persisted["applied"] is True
    assert persisted["applied_files"] == ["src/net.py"]
    assert persisted["applied_at"] == outcome.applied_at
    again = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert again.applied is True
    assert (again.error or "").lower().startswith("already")
    assert target.read_bytes() == expected
    assert list(cache.iter_edits()) == records
    assert json.loads((delegation / "result.json").read_text()) == persisted


@pytest.mark.parametrize("staged,error_fragment", [(False, "not found"), (True, "no diff")])
def test_apply_delegation_rejects_missing_or_empty_patch_without_edits(
    tmp_path, staged, error_fragment
):
    repo = _make_repo(tmp_path / "repo")
    did = "e" * 32
    before = (repo / "src/net.py").read_bytes()
    if staged:
        _stage_delegation(repo, did, patch_text="", result_payload={"delegation_id": did})
    outcome = apply_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert outcome.applied is False
    assert error_fragment in (outcome.error or "").lower()
    assert (repo / "src/net.py").read_bytes() == before
    assert not (repo / ".magi/sessions/s1/edits.jsonl").exists()


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


def test_discard_removes_real_worktree_and_preserves_durable_result(tmp_path, monkeypatch):
    import shutil
    from magi.tools.code_agent.workspace import create_worktree

    repo = _make_repo(tmp_path / "repo")
    did = "1" * 32
    worktree = create_worktree(workspace_root=repo, session_id="s1", delegation_id=did)
    assert worktree.exists()
    (worktree / "src/net.py").write_text("unapplied edit\n")
    delegation = _stage_delegation(
        repo, did, patch_text=_SAMPLE_PATCH, result_payload={"delegation_id": did, "success": True}
    )
    monkeypatch.setattr("magi.tools.code_agent.apply_diff.time.time", lambda: 1234.5)
    discard_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert not worktree.exists()
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(worktree) not in listing
    assert json.loads((delegation / "result.json").read_text()) == {
        "delegation_id": did,
        "success": True,
        "discarded_at": 1234500,
    }
    discard_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    shutil.rmtree(delegation)
    discard_delegation(workspace_root=repo, session_id="s1", delegation_id=did)
    assert not delegation.exists()
    assert (repo / "src/net.py").read_text() == "def connect():\n    return 1\n"


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
