"""Workspace-scoped path facade.

The facade keeps project-local files, project-local generated state, and the
private global workspace bucket behind one typed boundary. Runtime users should
ask for scoped paths here instead of assembling ``<workspace>/.magi`` manually.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ...utils.runtime import RuntimePaths, get_runtime_paths

WORKSPACE_DIRNAME = ".magi"
WORKSPACE_STATE_SCHEMA_VERSION = 1

_LOCAL_GITIGNORE_LINES = (
    "# Magi local workspace state",
    "/.gitignore",
    "local/",
    "cache/",
    "runtime/",
    "traces/",
    "*.tmp",
    "*.lock",
)


def normalize_workspace_root(workspace_root: str | Path) -> Path:
    """Resolve and validate a workspace root path."""
    resolved = Path(workspace_root).expanduser().resolve(strict=False)
    if resolved == resolved.parent:
        raise ValueError("workspace root must not be a filesystem root")
    return resolved


def compute_workspace_id(workspace_root: str | Path, fingerprint: str | None = None) -> str:
    """Return a stable private bucket id for a workspace root.

    ``fingerprint`` lets a future git-root/remote-aware caller add repository
    identity without changing the caller-facing path API.
    """
    normalized_root = str(normalize_workspace_root(workspace_root)).replace("\\", "/")
    identity_parts = [normalized_root]
    if fingerprint and fingerprint.strip():
        identity_parts.append(fingerprint.strip())
    digest = hashlib.sha256("\n".join(identity_parts).encode("utf-8")).hexdigest()[:32]
    return f"ws_{digest}"


def _safe_segment(raw_value: str, label: str) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        raise ValueError(f"{label} is required")
    normalized = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in raw)
    if normalized in {".", ".."}:
        raise ValueError(f"{label} is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Resolved paths for one workspace overlay."""

    workspace_root: Path
    runtime_paths: RuntimePaths
    workspace_id: str

    @classmethod
    def from_root(
        cls,
        workspace_root: str | Path,
        *,
        runtime_paths: RuntimePaths | None = None,
        workspace_id: str | None = None,
        fingerprint: str | None = None,
    ) -> "WorkspacePaths":
        """Create paths for a workspace root."""
        normalized_root = normalize_workspace_root(workspace_root)
        resolved_runtime_paths = runtime_paths or get_runtime_paths()
        resolved_workspace_id = workspace_id or compute_workspace_id(
            normalized_root,
            fingerprint,
        )
        return cls(
            workspace_root=normalized_root,
            runtime_paths=resolved_runtime_paths,
            workspace_id=_safe_segment(resolved_workspace_id, "workspace_id"),
        )

    @property
    def repo_state_dir(self) -> Path:
        """Project-local Magi overlay directory."""
        return self.workspace_root / WORKSPACE_DIRNAME

    @property
    def instructions_path(self) -> Path:
        """Team-shareable project instructions."""
        return self.repo_state_dir / "instructions.md"

    @property
    def settings_path(self) -> Path:
        """Team-shareable safe project settings."""
        return self.repo_state_dir / "settings.json"

    @property
    def rules_dir(self) -> Path:
        """Team-shareable path-scoped project rules."""
        return self.repo_state_dir / "rules"

    @property
    def skills_dir(self) -> Path:
        """Team-shareable project skills."""
        return self.repo_state_dir / "skills"

    @property
    def local_dir(self) -> Path:
        """Gitignored project-local state."""
        return self.repo_state_dir / "local"

    @property
    def local_settings_path(self) -> Path:
        """Gitignored personal settings for this workspace."""
        return self.local_dir / "settings.json"

    @property
    def state_path(self) -> Path:
        """Gitignored workspace state manifest."""
        return self.local_dir / "workspace-state.json"

    @property
    def cache_dir(self) -> Path:
        """Project-local rebuildable cache directory."""
        return self.repo_state_dir / "cache"

    @property
    def runtime_dir(self) -> Path:
        """Project-local task and tool runtime directory."""
        return self.repo_state_dir / "runtime"

    @property
    def traces_dir(self) -> Path:
        """Project-local lightweight trace artifacts."""
        return self.repo_state_dir / "traces"

    @property
    def global_bucket_dir(self) -> Path:
        """Private global bucket for heavy workspace-scoped data."""
        return self.runtime_paths.workspace_bucket_dir(self.workspace_id)

    @property
    def global_cache_dir(self) -> Path:
        """Private global rebuildable cache for this workspace."""
        return self.global_bucket_dir / "cache"

    @property
    def global_runtime_dir(self) -> Path:
        """Private global runtime state for this workspace."""
        return self.global_bucket_dir / "runtime"

    def code_index_cache_dir(self, *, global_scope: bool = True) -> Path:
        """Return the code-index cache directory."""
        base_dir = self.global_cache_dir if global_scope else self.cache_dir
        return base_dir / "code-index"

    def plugin_cache_dir(self, plugin_id: str, *, global_scope: bool = True) -> Path:
        """Return a plugin-scoped cache bucket for this workspace."""
        plugin_segment = _safe_segment(plugin_id, "plugin_id")
        base_dir = self.global_cache_dir if global_scope else self.cache_dir
        return base_dir / "plugins" / plugin_segment

    def task_runtime_dir(self, task_id: str, *, global_scope: bool = True) -> Path:
        """Return a task-scoped runtime bucket for this workspace."""
        task_segment = _safe_segment(task_id, "task_id")
        base_dir = self.global_runtime_dir if global_scope else self.runtime_dir
        return base_dir / "tasks" / task_segment

    def managed_generated_dirs(self) -> tuple[Path, ...]:
        """Return generated project-local directories maintenance may clean."""
        return (self.cache_dir, self.runtime_dir, self.traces_dir)

    def ensure_local_overlay(self) -> None:
        """Create the local generated overlay and its gitignore guard."""
        for directory in (
            self.repo_state_dir,
            self.local_dir,
            *self.managed_generated_dirs(),
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.ensure_repo_gitignore()

    def ensure_shared_config_dirs(self) -> None:
        """Create team-shareable config directories without writing content."""
        self.repo_state_dir.mkdir(parents=True, exist_ok=True)
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_repo_gitignore()

    def ensure_repo_gitignore(self) -> None:
        """Ensure generated workspace-local state is ignored under ``.magi``."""
        self.repo_state_dir.mkdir(parents=True, exist_ok=True)
        gitignore_path = self.repo_state_dir / ".gitignore"
        existing_lines: list[str] = []
        if gitignore_path.exists():
            existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()

        missing_lines = [line for line in _LOCAL_GITIGNORE_LINES if line not in existing_lines]
        if not missing_lines:
            return

        next_lines = [*existing_lines]
        if next_lines and next_lines[-1] != "":
            next_lines.append("")
        next_lines.extend(missing_lines)
        gitignore_path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")

    def ensure_global_bucket(self) -> None:
        """Create private global workspace cache/runtime directories."""
        for directory in (
            self.global_bucket_dir,
            self.global_cache_dir,
            self.global_runtime_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
