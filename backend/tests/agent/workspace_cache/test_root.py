"""Tests for WorkspaceCacheRoot."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache.contracts import SCHEMA_VERSION
from magi_plugin_sdk.workspace_cache.root import WorkspaceCacheRoot


def test_root_creates_directory_structure(tmp_path: Path) -> None:
    root = WorkspaceCacheRoot.ensure(tmp_path)
    cache_dir = tmp_path / ".magi"
    assert cache_dir.is_dir()
    assert (cache_dir / "sessions").is_dir()
    assert (cache_dir / ".gitignore").read_text() == "*\n"
    assert root.cache_dir == cache_dir
    assert root.sessions_dir == cache_dir / "sessions"


def test_root_writes_workspace_metadata(tmp_path: Path) -> None:
    WorkspaceCacheRoot.ensure(tmp_path)
    meta_path = tmp_path / ".magi" / "workspace.json"
    payload = json.loads(meta_path.read_text())
    assert payload["workspace_root"] == str(tmp_path.resolve())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["created_at_ms"] > 0


def test_root_reinitialization_preserves_existing_metadata_bytes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "magi_plugin_sdk.workspace_cache.root.time", SimpleNamespace(time=lambda: 100)
    )
    root = WorkspaceCacheRoot.ensure(tmp_path)
    metadata_path = root.cache_dir / "workspace.json"
    original = metadata_path.read_bytes()
    assert json.loads(original)["created_at_ms"] == 100000
    monkeypatch.setattr(
        "magi_plugin_sdk.workspace_cache.root.time", SimpleNamespace(time=lambda: 500)
    )
    again = WorkspaceCacheRoot.ensure(tmp_path)
    assert again == root
    assert metadata_path.read_bytes() == original


@pytest.mark.parametrize(
    "existing,expected",
    [
        (None, "/.magi/\n"),
        ("", "/.magi/\n"),
        ("node_modules/", "node_modules/\n/.magi/\n"),
        ("node_modules/\n", "node_modules/\n/.magi/\n"),
        ("# cache\n/.magi/\nnode_modules/\n", "# cache\n/.magi/\nnode_modules/\n"),
    ],
)
def test_root_updates_gitignore_without_losing_entries_or_duplicating_cache_rule(
    tmp_path, existing, expected
):
    project_gitignore = tmp_path / ".gitignore"
    if existing is not None:
        project_gitignore.write_text(existing)
    for _ in range(2):
        WorkspaceCacheRoot.ensure(tmp_path)
        assert project_gitignore.read_text() == expected


def test_root_rejects_non_existent_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        WorkspaceCacheRoot.ensure(missing)


def test_root_rejects_unsafe_session_id(tmp_path: Path) -> None:
    root = WorkspaceCacheRoot.ensure(tmp_path)
    for bad in ("../escape", "a/b", "with space", "", ".", ".."):
        with pytest.raises(ValueError):
            root.session_dir_for(bad)
