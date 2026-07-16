from __future__ import annotations

import json
import multiprocessing
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from magi.core.workspace import WorkspacePaths, WorkspaceStateStore
from magi.utils.runtime import RuntimePaths


def _claim_workspace_in_process(args: tuple[str, str]) -> str:
    workspace_root, runtime_root = args
    paths = WorkspacePaths.from_root(
        workspace_root,
        runtime_paths=RuntimePaths(base_dir=Path(runtime_root)),
    )
    return WorkspaceStateStore(paths).claim_identity().workspace_id


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


def test_workspace_state_store_touch_does_not_reenter_the_file_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    store = WorkspaceStateStore(WorkspacePaths.from_root(workspace_root))

    def _fail_reentrant_write(_state) -> None:
        raise AssertionError("touch must write under its existing workspace lock")

    monkeypatch.setattr(store, "write", _fail_reentrant_write)

    state = store.touch()

    assert store.read_persisted() == state


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


def test_workspace_state_store_ignores_an_invalid_persisted_root(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(workspace_root)
    paths.ensure_local_overlay()
    paths.state_path.write_text(
        json.dumps(
            {
                "workspaceId": "repo-main",
                "workspaceRoot": "\u0000invalid-root",
            }
        ),
        encoding="utf-8",
    )

    state = WorkspaceStateStore(paths).claim_identity()

    assert state.workspace_id != "repo-main"
    assert state.workspace_id != paths.workspace_id
    assert state.workspace_id.startswith("ws_")
    assert state.workspace_root == str(workspace_root)


def test_workspace_state_store_touch_preserves_durable_id(tmp_path: Path) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(workspace_root)
    store = WorkspaceStateStore(paths)

    first = store.touch()
    second = store.touch()

    assert first.workspace_id != paths.workspace_id
    assert first.workspace_id.startswith("ws_")
    assert second.workspace_id == first.workspace_id


def test_workspace_identity_claim_does_not_rewrite_a_matching_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(workspace_root)
    store = WorkspaceStateStore(paths)
    first = store.claim_identity()
    first_content = paths.state_path.read_text(encoding="utf-8")

    def _fail_write(_state) -> None:
        raise AssertionError("matching identity must not be rewritten")

    monkeypatch.setattr(store, "write", _fail_write)
    second = store.claim_identity()

    assert first.workspace_id != paths.workspace_id
    assert second == first
    assert paths.state_path.read_text(encoding="utf-8") == first_content


def test_workspace_state_store_preserves_id_after_move(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    original_state = WorkspaceStateStore(
        WorkspacePaths.from_root(original, workspace_id="repo-main")
    ).claim_identity()
    moved = tmp_path / "moved"
    shutil.move(str(original), str(moved))

    moved_state = WorkspaceStateStore(WorkspacePaths.from_root(moved)).rebind_identity(original)

    assert original_state.workspace_id == "repo-main"
    assert moved_state.workspace_id == "repo-main"
    assert moved_state.workspace_root == str(moved)


def test_workspace_state_store_assigns_new_id_to_a_live_copy(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    original_state = WorkspaceStateStore(WorkspacePaths.from_root(original)).claim_identity()
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)

    copied_state = WorkspaceStateStore(WorkspacePaths.from_root(copied)).claim_identity()
    original_after = WorkspaceStateStore(WorkspacePaths.from_root(original)).claim_identity()

    assert copied_state.workspace_id != original_state.workspace_id
    assert original_after.workspace_id == original_state.workspace_id


def test_workspace_rebind_does_not_preserve_id_when_prior_root_still_exists(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    original_state = WorkspaceStateStore(WorkspacePaths.from_root(original)).claim_identity()
    switched = tmp_path / "switched"
    shutil.copytree(original, switched)

    switched_state = WorkspaceStateStore(WorkspacePaths.from_root(switched)).rebind_identity(
        original
    )

    assert switched_state.workspace_id != original_state.workspace_id


def test_workspace_state_store_assigns_new_id_when_copy_outlives_source(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    original_state = WorkspaceStateStore(WorkspacePaths.from_root(original)).claim_identity()
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)
    shutil.rmtree(original)

    copied_state = WorkspaceStateStore(WorkspacePaths.from_root(copied)).claim_identity()

    assert copied_state.workspace_id != original_state.workspace_id


def test_workspace_touch_assigns_new_id_when_copy_outlives_source(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    original_state = WorkspaceStateStore(WorkspacePaths.from_root(original)).claim_identity()
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)
    shutil.rmtree(original)

    copied_state = WorkspaceStateStore(WorkspacePaths.from_root(copied)).touch()

    assert copied_state.workspace_id != original_state.workspace_id


def test_workspace_state_store_isolates_two_copies_after_source_deletion(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    original_state = WorkspaceStateStore(WorkspacePaths.from_root(original)).claim_identity()
    first_copy = tmp_path / "first-copy"
    second_copy = tmp_path / "second-copy"
    shutil.copytree(original, first_copy)
    shutil.copytree(original, second_copy)
    shutil.rmtree(original)

    first_state = WorkspaceStateStore(WorkspacePaths.from_root(first_copy)).claim_identity()
    second_state = WorkspaceStateStore(WorkspacePaths.from_root(second_copy)).claim_identity()

    assert first_state.workspace_id != original_state.workspace_id
    assert second_state.workspace_id != original_state.workspace_id
    assert first_state.workspace_id != second_state.workspace_id


def test_workspace_identity_claim_does_not_dirty_a_new_git_repository(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=workspace_root,
        check=True,
    )
    paths = WorkspacePaths.from_root(workspace_root)

    WorkspaceStateStore(paths).claim_identity()

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
    assert paths.state_path.is_file()
    assert not paths.cache_dir.exists()
    assert not paths.runtime_dir.exists()
    assert not paths.traces_dir.exists()


def test_workspace_identity_claim_does_not_modify_tracked_parent_gitignore(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=workspace_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=workspace_root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=workspace_root,
        check=True,
    )
    parent_ignore = workspace_root / ".magi" / ".gitignore"
    parent_ignore.parent.mkdir()
    parent_ignore.write_text("local/\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".magi/.gitignore"],
        cwd=workspace_root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test fixture"],
        cwd=workspace_root,
        check=True,
    )
    original_content = parent_ignore.read_text(encoding="utf-8")

    WorkspaceStateStore(WorkspacePaths.from_root(workspace_root)).claim_identity()

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
    assert parent_ignore.read_text(encoding="utf-8") == original_content


def test_concurrent_workspace_identity_claims_converge_on_one_id(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    paths = WorkspacePaths.from_root(workspace_root)

    with ThreadPoolExecutor(max_workers=8) as executor:
        states = list(
            executor.map(
                lambda _index: WorkspaceStateStore(paths).claim_identity(),
                range(32),
            )
        )

    assert len({state.workspace_id for state in states}) == 1
    assert WorkspaceStateStore(paths).read_persisted() == states[0]


def test_cross_process_workspace_identity_claims_converge_on_one_id(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    runtime_root = tmp_path / "runtime-home"
    inputs = [(str(workspace_root), str(runtime_root))] * 12

    with ProcessPoolExecutor(
        max_workers=4,
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        workspace_ids = list(executor.map(_claim_workspace_in_process, inputs))

    assert len(set(workspace_ids)) == 1
