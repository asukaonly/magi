"""Apply / discard a delegation's changes.patch in the main workspace.

Apply flow:
1. Locate the delegation directory and its ``changes.patch``.
2. Locate ``result.json``; if ``applied_at`` is already set, return early.
3. Snapshot the current bytes of every file the patch touches into the session
   cache so a subsequent ``file_rollback`` can undo the apply.
4. Run ``git apply --3way <changes.patch>`` in the main workspace.
5. On success, record an ``EditRecord`` per touched file and stamp ``applied_at``
   in result.json.
6. On failure, capture any ``.rej`` files left in the working tree.

Discard flow:
1. Remove the worktree (best-effort).
2. Stamp ``discarded_at`` in result.json.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from magi_plugin_sdk.fs import atomic_write_text
from magi_plugin_sdk.workspace_cache import resolve_session_cache
from .workspace import remove_worktree


@dataclass(frozen=True)
class ApplyOutcome:
    applied: bool
    files_applied: list[str] = field(default_factory=list)
    rejects: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "files_applied": list(self.files_applied),
            "rejects": list(self.rejects),
            "error": self.error,
        }


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)


def _delegation_dir(workspace_root: Path, session_id: str, delegation_id: str) -> Path:
    return workspace_root / ".magi" / "sessions" / session_id / "delegations" / delegation_id


def _read_result(delegation_dir: Path) -> dict:
    result_path = delegation_dir / "result.json"
    if not result_path.is_file():
        return {}
    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_result(delegation_dir: Path, payload: dict) -> None:
    atomic_write_text(delegation_dir / "result.json", json.dumps(payload))


def _files_in_patch(unified_diff: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _DIFF_HEADER_RE.finditer(unified_diff):
        path = match.group(2)
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def apply_delegation(
    *,
    workspace_root: Path,
    session_id: str,
    delegation_id: str,
) -> ApplyOutcome:
    workspace_root = Path(workspace_root).resolve()
    delegation_dir = _delegation_dir(workspace_root, session_id, delegation_id)
    if not delegation_dir.is_dir():
        return ApplyOutcome(applied=False, error=f"delegation not found: {delegation_id}")

    patch_path = delegation_dir / "changes.patch"
    if not patch_path.is_file() or not patch_path.read_text(encoding="utf-8").strip():
        return ApplyOutcome(applied=False, error="no diff to apply")

    result = _read_result(delegation_dir)
    if result.get("applied_at"):
        return ApplyOutcome(applied=True, error="already applied")

    patch_text = patch_path.read_text(encoding="utf-8")
    files = _files_in_patch(patch_text)

    sc = resolve_session_cache(workspace_root, session_id)

    pre_snapshots: list[tuple[str, str]] = []  # (path, sha256_before)
    for rel in files:
        target = workspace_root / rel
        try:
            data = target.read_bytes() if target.is_file() else b""
        except OSError:
            data = b""
        ref = sc.write_snapshot(data)
        pre_snapshots.append((rel, ref.sha256))

    proc = subprocess.run(
        ["git", "apply", "--3way", str(patch_path)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        # Clear any partially applied files from index
        subprocess.run(
            ["git", "reset", "--mixed"] + files,
            cwd=workspace_root,
            capture_output=True,
        )
        rejects = [
            str(p.relative_to(workspace_root))
            for p in workspace_root.rglob("*.rej")
        ]
        error_msg = proc.stderr.strip() or proc.stdout.strip() or "git apply failed"
        # Check for common errors and provide helpful hints
        if "does not match index" in error_msg:
            error_msg += (
                ". The working directory has uncommitted changes that differ from the worktree base. "
                "Commit or stash your changes, then try again."
            )
        elif "patch does not apply" in error_msg:
            error_msg += (
                ". The delegation's changes conflict with the current file contents. "
                "This usually happens when files were modified outside the delegation."
            )
        return ApplyOutcome(
            applied=False,
            rejects=rejects,
            error=error_msg,
        )

    import hashlib
    for rel, sha_before in pre_snapshots:
        target = workspace_root / rel
        try:
            after_bytes = target.read_bytes() if target.is_file() else b""
        except OSError:
            after_bytes = b""
        sha_after = hashlib.sha256(after_bytes).hexdigest()
        try:
            sc.record_edit(
                path=str(target),
                op="replace",
                sha256_before=sha_before,
                sha256_after=sha_after,
                snapshot_ref=sha_before,
            )
        except Exception:
            pass

    # Unstage files so they appear in working directory, not as staged changes
    if files:
        subprocess.run(
            ["git", "reset", "--mixed"] + files,
            cwd=workspace_root,
            capture_output=True,
        )

    if result:
        result["applied_at"] = int(time.time() * 1000)
        result["applied_files"] = files
        _write_result(delegation_dir, result)

    return ApplyOutcome(applied=True, files_applied=files)


def discard_delegation(
    *,
    workspace_root: Path,
    session_id: str,
    delegation_id: str,
) -> None:
    workspace_root = Path(workspace_root).resolve()
    delegation_dir = _delegation_dir(workspace_root, session_id, delegation_id)
    worktree_path = (
        workspace_root / ".magi" / "sessions" / session_id / "worktrees" / delegation_id
    )
    if worktree_path.is_dir():
        try:
            remove_worktree(workspace_root=workspace_root, worktree_path=worktree_path)
        except Exception:
            pass
    if delegation_dir.is_dir():
        result = _read_result(delegation_dir)
        if result:
            result["discarded_at"] = int(time.time() * 1000)
            _write_result(delegation_dir, result)


__all__ = ["ApplyOutcome", "apply_delegation", "discard_delegation"]
