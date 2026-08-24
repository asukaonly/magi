from pathlib import Path


def test_sdk_exposes_workspace_cache_api():
    from magi_plugin_sdk.workspace_cache import (  # noqa: F401
        EditOp, EditRecord, ReadRecord, SCHEMA_VERSION, SessionCache,
        SessionCacheCorruptError, SnapshotIntegrityError, SnapshotRef,
        WorkspaceCacheError, WorkspaceCacheRoot, WorkspaceMetadata,
        resolve_session_cache,
    )


def test_resolve_session_cache_roundtrip(tmp_path: Path):
    from magi_plugin_sdk.workspace_cache import resolve_session_cache

    sc = resolve_session_cache(str(tmp_path), "session-1")
    ref = sc.write_snapshot(b"hello")
    assert sc.read_snapshot(ref) == b"hello"
