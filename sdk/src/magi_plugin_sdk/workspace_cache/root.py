"""Workspace-rooted ``.magi/`` directory manager."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from magi_plugin_sdk.fs import atomic_write_text
from .contracts import SCHEMA_VERSION, WorkspaceMetadata


_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GITIGNORE_LINE = "/.magi/"


@dataclass(frozen=True)
class WorkspaceCacheRoot:
    workspace_root: Path
    cache_dir: Path
    sessions_dir: Path

    @classmethod
    def ensure(cls, workspace_root: str | Path) -> "WorkspaceCacheRoot":
        workspace_root = Path(workspace_root).resolve()
        if not workspace_root.is_dir():
            raise FileNotFoundError(f"workspace_root does not exist: {workspace_root}")

        cache_dir = workspace_root / ".magi"
        sessions_dir = cache_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        gitignore = cache_dir / ".gitignore"
        if not gitignore.exists():
            atomic_write_text(gitignore, "*\n")

        meta_path = cache_dir / "workspace.json"
        if not meta_path.exists():
            meta = WorkspaceMetadata(
                workspace_root=str(workspace_root),
                schema_version=SCHEMA_VERSION,
                created_at_ms=int(time.time() * 1000),
            )
            atomic_write_text(meta_path, meta.model_dump_json())

        cls._patch_project_gitignore(workspace_root)

        return cls(
            workspace_root=workspace_root,
            cache_dir=cache_dir,
            sessions_dir=sessions_dir,
        )

    def session_dir_for(self, session_id: str) -> Path:
        if not _SESSION_ID_RE.match(session_id):
            raise ValueError(
                f"session_id must match {_SESSION_ID_RE.pattern}, got {session_id!r}"
            )
        return self.sessions_dir / session_id

    @staticmethod
    def _patch_project_gitignore(workspace_root: Path) -> None:
        gi = workspace_root / ".gitignore"
        if not gi.exists():
            atomic_write_text(gi, _GITIGNORE_LINE + "\n")
            return
        existing = gi.read_text()
        lines = existing.splitlines()
        if any(line.strip() == _GITIGNORE_LINE for line in lines):
            return
        suffix = "" if existing.endswith("\n") or existing == "" else "\n"
        atomic_write_text(gi, existing + suffix + _GITIGNORE_LINE + "\n")
