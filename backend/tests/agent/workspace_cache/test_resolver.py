"""Tests for resolve_session_cache and the public package surface."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache import (
    SessionCache,
    WorkspaceCacheError,
    WorkspaceCacheRoot,
    resolve_session_cache,
)


def test_resolve_session_cache_returns_ready_session(tmp_path: Path) -> None:
    sc = resolve_session_cache(tmp_path, "session-1")
    assert isinstance(sc, SessionCache)
    assert isinstance(sc.root, WorkspaceCacheRoot)
    assert sc.session_id == "session-1"
    assert sc.session_dir.is_dir()


def test_resolve_session_cache_idempotent_for_same_session(tmp_path: Path) -> None:
    sc_a = resolve_session_cache(tmp_path, "s")
    sc_b = resolve_session_cache(tmp_path, "s")
    assert sc_a.session_dir == sc_b.session_dir


def test_resolve_session_cache_rejects_bad_session_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_session_cache(tmp_path, "../escape")


def test_public_exports_workspace_cache_error() -> None:
    assert issubclass(WorkspaceCacheError, Exception)
