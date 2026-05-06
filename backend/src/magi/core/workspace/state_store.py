"""State manifest for workspace overlays."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .paths import WORKSPACE_STATE_SCHEMA_VERSION, WorkspacePaths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_managed_paths(raw_value: Any) -> tuple[str, ...]:
    if not isinstance(raw_value, list):
        return ()
    values = [
        value.strip()
        for value in raw_value
        if isinstance(value, str) and value.strip()
    ]
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
        if not self.paths.state_path.exists():
            return WorkspaceState.initial(self.paths)
        try:
            payload = json.loads(self.paths.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return WorkspaceState.initial(self.paths)
        if not isinstance(payload, dict):
            return WorkspaceState.initial(self.paths)
        return WorkspaceState.from_dict(payload, self.paths)

    def write(self, state: WorkspaceState) -> None:
        """Persist state atomically."""
        self.paths.ensure_local_overlay()
        payload = (
            json.dumps(state.to_dict(), ensure_ascii=True, indent=2, sort_keys=True)
            + "\n"
        )
        temp_path = self.paths.state_path.with_suffix(f".tmp-{id(state):x}")
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(self.paths.state_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def touch(self, *, managed_paths: tuple[str, ...] | None = None) -> WorkspaceState:
        """Record that this workspace was seen and ensure generated dirs exist."""
        current = self.read()
        now = _utc_now()
        combined_managed_paths = tuple(
            sorted(dict.fromkeys([*current.managed_paths, *(managed_paths or ())]))
        )
        next_state = WorkspaceState(
            workspace_id=self.paths.workspace_id,
            workspace_root=str(self.paths.workspace_root),
            schema_version=WORKSPACE_STATE_SCHEMA_VERSION,
            created_at=current.created_at or now,
            last_seen_at=now,
            managed_paths=combined_managed_paths,
        )
        self.write(next_state)
        return next_state
