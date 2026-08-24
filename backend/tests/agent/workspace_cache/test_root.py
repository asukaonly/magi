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


def test_root_is_idempotent(tmp_path: Path) -> None:
    root_a = WorkspaceCacheRoot.ensure(tmp_path)
    created_at_a = json.loads((tmp_path / ".magi" / "workspace.json").read_text())["created_at_ms"]
    root_b = WorkspaceCacheRoot.ensure(tmp_path)
    created_at_b = json.loads((tmp_path / ".magi" / "workspace.json").read_text())["created_at_ms"]
    assert root_a.cache_dir == root_b.cache_dir
    assert created_at_a == created_at_b, "metadata must not be rewritten on re-ensure"


def test_root_appends_to_existing_project_gitignore(tmp_path: Path) -> None:
    project_gitignore = tmp_path / ".gitignore"
    project_gitignore.write_text("node_modules/\n")
    WorkspaceCacheRoot.ensure(tmp_path)
    contents = project_gitignore.read_text()
    assert "node_modules/" in contents
    assert "/.magi/" in contents


def test_root_creates_project_gitignore_if_missing(tmp_path: Path) -> None:
    project_gitignore = tmp_path / ".gitignore"
    assert not project_gitignore.exists()
    WorkspaceCacheRoot.ensure(tmp_path)
    contents = project_gitignore.read_text()
    assert contents.strip() == "/.magi/"


def test_root_does_not_duplicate_gitignore_entry(tmp_path: Path) -> None:
    project_gitignore = tmp_path / ".gitignore"
    project_gitignore.write_text("/.magi/\n")
    WorkspaceCacheRoot.ensure(tmp_path)
    occurrences = project_gitignore.read_text().count("/.magi/")
    assert occurrences == 1


def test_root_rejects_non_existent_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        WorkspaceCacheRoot.ensure(missing)


def test_root_session_dir_for_returns_path(tmp_path: Path) -> None:
    root = WorkspaceCacheRoot.ensure(tmp_path)
    session_dir = root.session_dir_for("session-abc")
    assert session_dir == tmp_path / ".magi" / "sessions" / "session-abc"


def test_root_rejects_unsafe_session_id(tmp_path: Path) -> None:
    root = WorkspaceCacheRoot.ensure(tmp_path)
    for bad in ("../escape", "a/b", "with space", "", ".", ".."):
        with pytest.raises(ValueError):
            root.session_dir_for(bad)
