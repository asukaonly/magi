"""Tests for workspace cache error hierarchy."""

from magi_plugin_sdk.workspace_cache.errors import (
    WorkspaceCacheError,
    SnapshotIntegrityError,
    SessionCacheCorruptError,
)


def test_snapshot_integrity_is_workspace_cache_error():
    err = SnapshotIntegrityError("bad hash")
    assert isinstance(err, WorkspaceCacheError)


def test_session_cache_corrupt_is_workspace_cache_error():
    err = SessionCacheCorruptError("bad jsonl line")
    assert isinstance(err, WorkspaceCacheError)


def test_workspace_cache_error_str_round_trip():
    err = WorkspaceCacheError("base failure")
    assert str(err) == "base failure"
