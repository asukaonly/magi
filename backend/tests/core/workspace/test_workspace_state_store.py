from __future__ import annotations

from pathlib import Path

from magi.core.workspace import WorkspacePaths, WorkspaceStateStore
from magi.utils.runtime import RuntimePaths


def test_workspace_state_store_returns_initial_state_without_writing(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "home" / ".magi")
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(
        workspace_root,
        runtime_paths=runtime_paths,
        workspace_id="workspace-1",
    )
    store = WorkspaceStateStore(paths)

    state = store.read()

    assert state.workspace_id == "workspace-1"
    assert state.workspace_root == str(workspace_root)
    assert state.created_at is None
    assert not paths.state_path.exists()


def test_workspace_state_store_touch_writes_manifest_and_dirs(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "home" / ".magi")
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(
        workspace_root,
        runtime_paths=runtime_paths,
        workspace_id="workspace-1",
    )
    store = WorkspaceStateStore(paths)

    state = store.touch(managed_paths=("cache/plugins/core-tools",))
    reread = store.read()

    assert paths.state_path.exists()
    assert state.created_at is not None
    assert state.last_seen_at is not None
    assert reread.workspace_id == "workspace-1"
    assert "cache" in reread.managed_paths
    assert "cache/plugins/core-tools" in reread.managed_paths
    assert (paths.repo_state_dir / ".gitignore").exists()


def test_workspace_state_store_recovers_from_invalid_manifest(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / "home" / ".magi")
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(workspace_root, runtime_paths=runtime_paths)
    paths.ensure_local_overlay()
    paths.state_path.write_text("not-json", encoding="utf-8")

    state = WorkspaceStateStore(paths).read()

    assert state.workspace_id == paths.workspace_id
    assert state.created_at is None
