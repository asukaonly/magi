"""State manifest for workspace overlays."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from magi_plugin_sdk.subprocess import hidden_process_kwargs
from .paths import WORKSPACE_STATE_SCHEMA_VERSION, WorkspacePaths, compute_workspace_id

_STATE_LOCKS_GUARD = threading.Lock()
_STATE_LOCKS: dict[str, Any] = {}


def _process_state_lock(state_path: Path):
    key = str(state_path.resolve(strict=False))
    with _STATE_LOCKS_GUARD:
        return _STATE_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _file_lock(lock_path: Path):
    """Hold a cross-process advisory lock for one workspace state file."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _workspace_state_lock(paths: WorkspacePaths):
    """Serialize state changes in this process and across Magi processes."""
    lock_path = (
        paths.runtime_paths.runtime_dir
        / "workspace-identity-locks"
        / f"{compute_workspace_id(paths.workspace_root)}.lock"
    )
    with _process_state_lock(paths.state_path):
        with _file_lock(lock_path):
            yield


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_managed_paths(raw_value: Any) -> tuple[str, ...]:
    if not isinstance(raw_value, list):
        return ()
    values = [value.strip() for value in raw_value if isinstance(value, str) and value.strip()]
    return tuple(sorted(dict.fromkeys(values)))


@dataclass(frozen=True, slots=True)
class WorkspaceState:
    """Serializable workspace-local state manifest."""

    workspace_id: str
    workspace_root: str
    schema_version: int = WORKSPACE_STATE_SCHEMA_VERSION
    created_at: str | None = None
    last_seen_at: str | None = None
    managed_paths: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def initial(cls, paths: WorkspacePaths) -> "WorkspaceState":
        """Build an in-memory state for a workspace without creating files."""
        return cls(
            workspace_id=paths.workspace_id,
            workspace_root=str(paths.workspace_root),
            managed_paths=tuple(
                str(directory.relative_to(paths.repo_state_dir)).replace("\\", "/")
                for directory in paths.managed_generated_dirs()
            ),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any], paths: WorkspacePaths) -> "WorkspaceState":
        """Parse a persisted state manifest with safe defaults."""
        schema_version = payload.get("schemaVersion")
        if not isinstance(schema_version, int):
            schema_version = WORKSPACE_STATE_SCHEMA_VERSION
        return cls(
            workspace_id=str(payload.get("workspaceId") or paths.workspace_id),
            workspace_root=str(payload.get("workspaceRoot") or paths.workspace_root),
            schema_version=schema_version,
            created_at=payload.get("createdAt")
            if isinstance(payload.get("createdAt"), str)
            else None,
            last_seen_at=payload.get("lastSeenAt")
            if isinstance(payload.get("lastSeenAt"), str)
            else None,
            managed_paths=_coerce_managed_paths(payload.get("managedPaths")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON representation."""
        return {
            "schemaVersion": self.schema_version,
            "workspaceId": self.workspace_id,
            "workspaceRoot": self.workspace_root,
            "createdAt": self.created_at,
            "lastSeenAt": self.last_seen_at,
            "managedPaths": list(self.managed_paths),
        }


class WorkspaceStateStore:
    """Read and write the workspace-local state manifest."""

    def __init__(self, paths: WorkspacePaths):
        self.paths = paths

    def read(self) -> WorkspaceState:
        """Read state, returning an initial state when the file is absent or invalid."""
        persisted = self._read_persisted()
        return persisted or WorkspaceState.initial(self.paths)

    def read_persisted(self) -> WorkspaceState | None:
        """Read only a complete on-disk state manifest, if one exists."""
        return self._read_persisted()

    def _read_persisted(self) -> WorkspaceState | None:
        if not self.paths.state_path.exists():
            return None
        try:
            payload = json.loads(self.paths.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if (
            not isinstance(payload.get("workspaceId"), str)
            or not str(payload["workspaceId"]).strip()
        ):
            return None
        if (
            not isinstance(payload.get("workspaceRoot"), str)
            or not str(payload["workspaceRoot"]).strip()
        ):
            return None
        return WorkspaceState.from_dict(payload, self.paths)

    def write(self, state: WorkspaceState) -> None:
        """Persist state atomically."""
        with _workspace_state_lock(self.paths):
            self.paths.ensure_local_overlay()
            self._write_payload(state)

    def _write_identity_state(self, state: WorkspaceState) -> None:
        """Persist only the files required for a durable identity claim."""
        self._ensure_identity_state_ignored()
        self._write_payload(state)

    def _ensure_identity_state_ignored(self) -> None:
        """Prepare a self-ignored local directory without changing shared files."""
        self.paths.local_dir.mkdir(parents=True, exist_ok=True)
        local_ignore_path = self.paths.local_dir / ".gitignore"
        created_ignore = False
        if not local_ignore_path.exists():
            local_ignore_path.write_text("*\n", encoding="utf-8")
            created_ignore = True
        try:
            ignored = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.paths.workspace_root),
                    "check-ignore",
                    "--quiet",
                    "--",
                    str(self.paths.state_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                **hidden_process_kwargs(),
            )
            if ignored.returncode == 0:
                return
            if ignored.returncode == 128:
                return
            if ignored.returncode == 1:
                raise OSError("Workspace identity state must be ignored by git")
            raise OSError("Unable to verify workspace identity ignore state")
        except FileNotFoundError:
            return
        except BaseException:
            if created_ignore:
                local_ignore_path.unlink(missing_ok=True)
            raise

    def _write_payload(self, state: WorkspaceState) -> None:
        """Write one prepared state payload atomically."""
        payload = json.dumps(state.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        temp_path = self.paths.state_path.with_suffix(f".tmp-{id(state):x}")
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(self.paths.state_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def claim_identity(self) -> WorkspaceState:
        """Persist identity only when the workspace has not been claimed here."""
        with _workspace_state_lock(self.paths):
            return self._claim_identity_unlocked()

    def _claim_identity_unlocked(self) -> WorkspaceState:
        """Claim identity while the workspace state lock is held."""
        persisted = self.read_persisted()
        if persisted is not None:
            try:
                previous_root = Path(persisted.workspace_root).expanduser().resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                pass
            else:
                if previous_root == self.paths.workspace_root:
                    return persisted
        return self._write_new_identity_claim()

    def rebind_identity(self, previous_root: str | Path) -> WorkspaceState:
        """Preserve identity for one explicit move from a known prior root."""
        with _workspace_state_lock(self.paths):
            return self._rebind_identity_unlocked(previous_root)

    def _rebind_identity_unlocked(self, previous_root: str | Path) -> WorkspaceState:
        """Rebind identity while the workspace state lock is held."""
        persisted = self.read_persisted()
        if persisted is None:
            return self._write_new_identity_claim()
        try:
            persisted_root = Path(persisted.workspace_root).expanduser().resolve(strict=False)
            expected_previous_root = Path(previous_root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return self._write_new_identity_claim()
        if persisted_root == self.paths.workspace_root:
            return persisted
        if persisted_root == expected_previous_root and not expected_previous_root.exists():
            return self._write_moved_identity_claim(persisted)
        return self._write_new_identity_claim()

    def _write_moved_identity_claim(self, persisted: WorkspaceState) -> WorkspaceState:
        """Move an existing claim to its new root without changing identity."""
        now = _utc_now()
        state = WorkspaceState(
            workspace_id=persisted.workspace_id,
            workspace_root=str(self.paths.workspace_root),
            schema_version=WORKSPACE_STATE_SCHEMA_VERSION,
            created_at=persisted.created_at or now,
            last_seen_at=now,
            managed_paths=persisted.managed_paths,
        )
        self._write_identity_state(state)
        return state

    def _write_new_identity_claim(self) -> WorkspaceState:
        """Write a path-independent identity for a new or copied workspace."""
        now = _utc_now()
        default_workspace_id = compute_workspace_id(self.paths.workspace_root)
        workspace_id = (
            self.paths.workspace_id
            if self.paths.workspace_id != default_workspace_id
            else f"ws_{uuid.uuid4().hex}"
        )
        initial = WorkspaceState.initial(self.paths)
        state = WorkspaceState(
            workspace_id=workspace_id,
            workspace_root=str(self.paths.workspace_root),
            schema_version=WORKSPACE_STATE_SCHEMA_VERSION,
            created_at=now,
            last_seen_at=now,
            managed_paths=initial.managed_paths,
        )
        self._write_identity_state(state)
        return state

    def touch(self, *, managed_paths: tuple[str, ...] | None = None) -> WorkspaceState:
        """Record that this workspace was seen and ensure generated dirs exist."""
        with _workspace_state_lock(self.paths):
            return self._touch_unlocked(managed_paths=managed_paths)

    def _touch_unlocked(
        self,
        *,
        managed_paths: tuple[str, ...] | None = None,
    ) -> WorkspaceState:
        """Touch state while the workspace state lock is held."""
        current = self._claim_identity_unlocked()
        now = _utc_now()
        combined_managed_paths = tuple(
            sorted(dict.fromkeys([*current.managed_paths, *(managed_paths or ())]))
        )
        next_state = WorkspaceState(
            workspace_id=current.workspace_id,
            workspace_root=str(self.paths.workspace_root),
            schema_version=WORKSPACE_STATE_SCHEMA_VERSION,
            created_at=current.created_at or now,
            last_seen_at=now,
            managed_paths=combined_managed_paths,
        )
        self.paths.ensure_local_overlay()
        self._write_payload(next_state)
        return next_state
