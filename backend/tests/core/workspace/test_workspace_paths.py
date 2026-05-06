from __future__ import annotations

from pathlib import Path

import pytest

from magi.core.workspace import (
    WorkspacePaths,
    compute_workspace_id,
    normalize_workspace_root,
)
from magi.utils.runtime import RuntimePaths


def test_workspace_paths_separate_shared_local_and_global_buckets(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "home" / ".magi")
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()

    paths = WorkspacePaths.from_root(
        workspace_root,
        runtime_paths=runtime_paths,
        workspace_id="repo-main",
    )

    assert paths.repo_state_dir == workspace_root / ".magi"
    assert paths.instructions_path == workspace_root / ".magi" / "instructions.md"
    assert paths.settings_path == workspace_root / ".magi" / "settings.json"
    assert paths.local_settings_path == workspace_root / ".magi" / "local" / "settings.json"
    assert paths.state_path == workspace_root / ".magi" / "local" / "workspace-state.json"
    assert paths.code_index_cache_dir() == (
        runtime_paths.workspaces_dir / "repo-main" / "cache" / "code-index"
    )
    assert paths.plugin_cache_dir("core/tools") == (
        runtime_paths.workspaces_dir / "repo-main" / "cache" / "plugins" / "core_tools"
    )
    assert paths.task_runtime_dir("task/1") == (
        runtime_paths.workspaces_dir / "repo-main" / "runtime" / "tasks" / "task_1"
    )
    assert paths.plugin_cache_dir("core-tools", global_scope=False) == (
        workspace_root / ".magi" / "cache" / "plugins" / "core-tools"
    )


def test_workspace_paths_create_gitignored_local_overlay(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "home" / ".magi")
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(workspace_root, runtime_paths=runtime_paths)

    paths.ensure_local_overlay()

    assert paths.local_dir.is_dir()
    assert paths.cache_dir.is_dir()
    assert paths.runtime_dir.is_dir()
    assert paths.traces_dir.is_dir()
    gitignore = (paths.repo_state_dir / ".gitignore").read_text(encoding="utf-8")
    assert "local/" in gitignore
    assert "cache/" in gitignore
    assert "runtime/" in gitignore
    assert "traces/" in gitignore


def test_workspace_identity_rejects_filesystem_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="workspace root"):
        normalize_workspace_root(Path(tmp_path.anchor))


def test_compute_workspace_id_is_stable_for_same_root(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()

    first = compute_workspace_id(workspace_root)
    second = compute_workspace_id(workspace_root)

    assert first == second
    assert first.startswith("ws_")
