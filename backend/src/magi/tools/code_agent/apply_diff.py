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

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field

from magi_plugin_sdk.subprocess import hidden_process_kwargs
from pathlib import Path
from typing import Optional

from magi_plugin_sdk.fs import atomic_write_bytes, atomic_write_text
from magi_plugin_sdk.workspace_cache import EditRecord, resolve_session_cache
from magi_plugin_sdk.workspace_cache.contracts import SnapshotRef

from ...core.code_agent_artifacts import (
    CodeAgentArtifactLocator,
    CodeAgentArtifactPathError,
)
from .workspace import remove_worktree


@dataclass(frozen=True)
class ApplyOutcome:
    applied: bool
    files_applied: list[str] = field(default_factory=list)
    rejects: list[str] = field(default_factory=list)
    error: Optional[str] = None
    applied_at: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "files_applied": list(self.files_applied),
            "rejects": list(self.rejects),
            "error": self.error,
            "applied_at": self.applied_at,
        }


@dataclass(frozen=True)
class _ApplyPaths:
    workspace_root: Path
    delegation_dir: Path
    patch_path: Path
    result_path: Path


@dataclass(frozen=True)
class _PreSnapshot:
    path: str
    sha256_before: str
    existed_before: bool


def _read_result(result_path: Path) -> dict:
    if not result_path.is_file():
        return {}
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_result(result_path: Path, payload: dict) -> None:
    atomic_write_text(result_path, json.dumps(payload))


def _files_in_patch(
    workspace_root: Path,
    patch_path: Path,
    patch_text: str,
) -> tuple[list[str], str | None]:
    proc = subprocess.run(
        ["git", "apply", "--numstat", "-z", str(patch_path)],
        cwd=workspace_root,
        capture_output=True,
        check=False,
        **hidden_process_kwargs(),
    )
    if proc.returncode != 0:
        error = proc.stderr.decode("utf-8", errors="replace").strip()
        return [], error or "delegation patch could not be parsed"

    files: list[str] = []
    records = proc.stdout.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            return [], "delegation patch has invalid path metadata"
        raw_path = fields[2]
        if raw_path:
            files.append(os.fsdecode(raw_path))
            continue
        if index + 1 >= len(records):
            return [], "delegation patch has incomplete rename metadata"
        old_path = records[index]
        new_path = records[index + 1]
        if not old_path or not new_path:
            return [], "delegation patch has incomplete rename metadata"
        files.extend((os.fsdecode(old_path), os.fsdecode(new_path)))
        index += 2
    rename_sources, rename_error = _rename_sources_in_patch(patch_text)
    if rename_error is not None:
        return [], rename_error
    return list(dict.fromkeys([*rename_sources, *files])), None


def _decode_git_metadata_path(raw_path: str) -> str | None:
    if not raw_path.startswith('"'):
        return raw_path
    if len(raw_path) < 2 or not raw_path.endswith('"'):
        return None

    escape_bytes = {
        "a": 0x07,
        "b": 0x08,
        "t": 0x09,
        "n": 0x0A,
        "v": 0x0B,
        "f": 0x0C,
        "r": 0x0D,
        '"': 0x22,
        "\\": 0x5C,
    }
    decoded = bytearray()
    body = raw_path[1:-1]
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            decoded.extend(char.encode("utf-8", errors="surrogateescape"))
            index += 1
            continue
        index += 1
        if index >= len(body):
            return None
        escaped = body[index]
        if escaped in escape_bytes:
            decoded.append(escape_bytes[escaped])
            index += 1
            continue
        if escaped not in "01234567":
            return None
        octal_end = index
        while octal_end < min(index + 3, len(body)) and body[octal_end] in "01234567":
            octal_end += 1
        decoded.append(int(body[index:octal_end], 8))
        index = octal_end
    return os.fsdecode(bytes(decoded))


def _rename_sources_in_patch(patch_text: str) -> tuple[list[str], str | None]:
    sources: list[str] = []
    for line in patch_text.splitlines():
        if not line.startswith("rename from "):
            continue
        decoded = _decode_git_metadata_path(line.removeprefix("rename from "))
        if decoded is None:
            return [], "delegation patch has invalid rename metadata"
        sources.append(decoded)
    return sources, None


def _has_unsupported_file_mode(patch_text: str) -> bool:
    unsupported_modes = ("mode 120000", "mode 160000")
    return any(
        line.strip().endswith(unsupported_modes)
        for line in patch_text.splitlines()
    )


def _validate_patch_files(workspace_root: Path, files: list[str]) -> list[str]:
    validated: list[str] = []
    for raw_path in files:
        relative_path = Path(raw_path)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not relative_path.parts
            or relative_path.parts[0] in {".git", ".magi"}
        ):
            raise CodeAgentArtifactPathError(
                "delegation patch contains a path outside the workspace"
            )
        expected_target = workspace_root / relative_path
        target = expected_target.resolve(strict=False)
        try:
            target.relative_to(workspace_root)
        except ValueError as exc:
            raise CodeAgentArtifactPathError(
                "delegation patch contains a path outside the workspace"
            ) from exc
        if target != expected_target:
            raise CodeAgentArtifactPathError(
                "delegation patch contains a symbolic-link path"
            )
        if target.exists() and not target.is_file():
            raise CodeAgentArtifactPathError(
                "delegation patch target is not a regular file"
            )
        validated.append(relative_path.as_posix())
    return validated


def _apply_paths(workspace_root: Path, session_id: str, delegation_id: str) -> _ApplyPaths:
    locator = CodeAgentArtifactLocator.resolve(
        workspace_root=workspace_root,
        session_id=session_id,
        delegation_id=delegation_id,
    )
    delegation_dir = locator.existing_delegation_dir()
    if delegation_dir is None:
        delegation_dir = locator.delegation_dir
        patch_path = delegation_dir / "changes.patch"
        result_path = delegation_dir / "result.json"
    else:
        patch_path = locator.artifact_file(
            "changes.patch",
            require_delegation=True,
        )
        result_path = locator.artifact_file(
            "result.json",
            require_delegation=True,
        )
    return _ApplyPaths(
        workspace_root=locator.workspace_root,
        delegation_dir=delegation_dir,
        patch_path=patch_path,
        result_path=result_path,
    )


def _read_non_empty_patch(patch_path: Path) -> str | None:
    if not patch_path.is_file():
        return None
    patch_text = patch_path.read_text(encoding="utf-8")
    if not patch_text.strip():
        return None
    return patch_text


def _snapshot_patch_files(
    *,
    workspace_root: Path,
    session_id: str,
    files: list[str],
) -> list[_PreSnapshot]:
    session_cache = resolve_session_cache(workspace_root, session_id)
    snapshots: list[_PreSnapshot] = []
    for rel in files:
        target = workspace_root / rel
        existed_before = target.is_file()
        data = target.read_bytes() if existed_before else b""
        ref = session_cache.write_snapshot(data)
        snapshots.append(
            _PreSnapshot(
                path=rel,
                sha256_before=ref.sha256,
                existed_before=existed_before,
            )
        )
    return snapshots


def _restore_patch_files(
    *,
    workspace_root: Path,
    session_id: str,
    snapshots: list[_PreSnapshot],
) -> None:
    session_cache = resolve_session_cache(workspace_root, session_id)
    for snapshot in snapshots:
        target = workspace_root / snapshot.path
        if snapshot.existed_before:
            data = session_cache.read_snapshot(
                SnapshotRef(sha256=snapshot.sha256_before)
            )
            atomic_write_bytes(target, data)
        elif target.exists() or target.is_symlink():
            if target.is_dir():
                raise RuntimeError(
                    "failed delegation apply created a directory at a file path"
                )
            target.unlink()


def _run_git_apply(workspace_root: Path, patch_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "apply", "--3way", str(patch_path)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        **hidden_process_kwargs(),
    )


def _reset_mixed(workspace_root: Path, files: list[str]) -> None:
    subprocess.run(
        ["git", "reset", "--mixed", "--", *files],
        cwd=workspace_root,
        capture_output=True,
        **hidden_process_kwargs(),
    )


def _reject_paths(workspace_root: Path) -> list[str]:
    return [str(p.relative_to(workspace_root)) for p in workspace_root.rglob("*.rej")]


def _apply_error(proc: subprocess.CompletedProcess[str]) -> str:
    error_msg = proc.stderr.strip() or proc.stdout.strip() or "git apply failed"
    if "does not match index" in error_msg:
        return (
            error_msg
            + ". The working directory has uncommitted changes that differ from the worktree base. "
            "Commit or stash your changes, then try again."
        )
    if "patch does not apply" in error_msg:
        return (
            error_msg + ". The delegation's changes conflict with the current file contents. "
            "This usually happens when files were modified outside the delegation."
        )
    return error_msg


def _failed_apply_outcome(
    *,
    workspace_root: Path,
    session_id: str,
    files: list[str],
    snapshots: list[_PreSnapshot],
    proc: subprocess.CompletedProcess[str],
) -> ApplyOutcome:
    _reset_mixed(workspace_root, files)
    _restore_patch_files(
        workspace_root=workspace_root,
        session_id=session_id,
        snapshots=snapshots,
    )
    return ApplyOutcome(
        applied=False,
        rejects=_reject_paths(workspace_root),
        error=_apply_error(proc),
    )


def _record_applied_edits(
    *,
    workspace_root: Path,
    session_id: str,
    snapshots: list[_PreSnapshot],
) -> None:
    session_cache = resolve_session_cache(workspace_root, session_id)
    applied_at = int(time.time() * 1000)
    records: list[EditRecord] = []
    for snapshot in snapshots:
        target = workspace_root / snapshot.path
        after_bytes = target.read_bytes() if target.is_file() else b""
        sha_after = hashlib.sha256(after_bytes).hexdigest()
        records.append(
            EditRecord(
                path=snapshot.path,
                op="replace",
                sha256_before=snapshot.sha256_before,
                sha256_after=sha_after,
                snapshot_ref=snapshot.sha256_before,
                ts_ms=applied_at,
            )
        )
    session_cache.record_edits(records)


def _stamp_applied(result_path: Path, result: dict, files: list[str]) -> int | None:
    if not result:
        return None
    applied_at = int(time.time() * 1000)
    result["applied"] = True
    result["applied_at"] = applied_at
    result["applied_files"] = files
    _write_result(result_path, result)
    return applied_at


def apply_delegation(
    *,
    workspace_root: Path,
    session_id: str,
    delegation_id: str,
) -> ApplyOutcome:
    paths = _apply_paths(workspace_root, session_id, delegation_id)
    if not paths.delegation_dir.is_dir():
        return ApplyOutcome(applied=False, error=f"delegation not found: {delegation_id}")

    patch_text = _read_non_empty_patch(paths.patch_path)
    if patch_text is None:
        return ApplyOutcome(applied=False, error="no diff to apply")
    if _has_unsupported_file_mode(patch_text):
        return ApplyOutcome(
            applied=False,
            error="delegation patch contains an unsupported special file",
        )

    result = _read_result(paths.result_path)
    if not result:
        return ApplyOutcome(
            applied=False,
            error="delegation result is missing or invalid",
        )
    if result.get("applied_at"):
        raw_applied_files = result.get("applied_files")
        applied_files = raw_applied_files if isinstance(raw_applied_files, list) else []
        try:
            stored_applied_at = int(result["applied_at"])
        except (TypeError, ValueError):
            return ApplyOutcome(
                applied=False,
                error="delegation result has an invalid applied timestamp",
            )
        return ApplyOutcome(
            applied=True,
            files_applied=[
                str(path)
                for path in applied_files
                if str(path or "").strip()
            ],
            error="already applied",
            applied_at=stored_applied_at,
        )

    parsed_files, parse_error = _files_in_patch(
        paths.workspace_root,
        paths.patch_path,
        patch_text,
    )
    if parse_error is not None:
        return ApplyOutcome(applied=False, error=parse_error)
    if not parsed_files:
        return ApplyOutcome(
            applied=False,
            error="delegation patch contains no file changes",
        )
    files = _validate_patch_files(paths.workspace_root, parsed_files)
    snapshots = _snapshot_patch_files(
        workspace_root=paths.workspace_root,
        session_id=session_id,
        files=files,
    )

    proc = _run_git_apply(paths.workspace_root, paths.patch_path)
    if proc.returncode != 0:
        return _failed_apply_outcome(
            workspace_root=paths.workspace_root,
            session_id=session_id,
            files=files,
            snapshots=snapshots,
            proc=proc,
        )

    # Unstage files so they appear in working directory, not as staged changes
    if files:
        _reset_mixed(paths.workspace_root, files)

    result_before_apply = dict(result)
    try:
        new_applied_at = _stamp_applied(paths.result_path, result, files)
    except Exception:
        _reset_mixed(paths.workspace_root, files)
        _restore_patch_files(
            workspace_root=paths.workspace_root,
            session_id=session_id,
            snapshots=snapshots,
        )
        raise
    if new_applied_at is None:  # pragma: no cover - result is required above
        raise RuntimeError("applied delegation is missing its timestamp")
    try:
        _record_applied_edits(
            workspace_root=paths.workspace_root,
            session_id=session_id,
            snapshots=snapshots,
        )
    except Exception as exc:
        recovery_errors: list[str] = []
        try:
            _reset_mixed(paths.workspace_root, files)
            _restore_patch_files(
                workspace_root=paths.workspace_root,
                session_id=session_id,
                snapshots=snapshots,
            )
        except Exception as recovery_exc:
            recovery_errors.append(f"workspace: {recovery_exc}")
        try:
            _write_result(paths.result_path, result_before_apply)
        except Exception as recovery_exc:
            recovery_errors.append(f"result: {recovery_exc}")
        if recovery_errors:
            raise RuntimeError(
                "edit ledger write failed and apply recovery was incomplete: "
                + "; ".join(recovery_errors)
            ) from exc
        return ApplyOutcome(
            applied=False,
            error=(
                "delegation apply could not record rollback history; "
                "workspace changes were reverted"
            ),
        )
    return ApplyOutcome(
        applied=True,
        files_applied=files,
        applied_at=new_applied_at,
    )


def discard_delegation(
    *,
    workspace_root: Path,
    session_id: str,
    delegation_id: str,
) -> None:
    locator = CodeAgentArtifactLocator.resolve(
        workspace_root=workspace_root,
        session_id=session_id,
        delegation_id=delegation_id,
    )
    worktree_path = locator.existing_worktree_dir()
    if worktree_path is not None:
        remove_worktree(
            workspace_root=locator.workspace_root,
            worktree_path=worktree_path,
        )
    delegation_dir = locator.existing_delegation_dir()
    if delegation_dir is not None:
        result_path = locator.artifact_file(
            "result.json",
            require_delegation=True,
        )
        result = _read_result(result_path)
        if result:
            result["discarded_at"] = int(time.time() * 1000)
            _write_result(result_path, result)


__all__ = ["ApplyOutcome", "apply_delegation", "discard_delegation"]
