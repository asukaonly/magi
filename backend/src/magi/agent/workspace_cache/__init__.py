"""Session-scoped workspace cache under ``<workspace_root>/.magi/``.

This package is now a thin re-export shim. The canonical implementation lives
in ``magi_plugin_sdk.workspace_cache``.
"""
from magi_plugin_sdk.workspace_cache import (
    EditOp,
    EditRecord,
    ReadRecord,
    SCHEMA_VERSION,
    SessionCache,
    SessionCacheCorruptError,
    SnapshotIntegrityError,
    SnapshotRef,
    TodoItem,
    TodoState,
    WorkspaceCacheError,
    WorkspaceCacheRoot,
    WorkspaceMetadata,
    resolve_session_cache,
)

__all__ = [
    "EditOp",
    "EditRecord",
    "ReadRecord",
    "SCHEMA_VERSION",
    "SessionCache",
    "SessionCacheCorruptError",
    "SnapshotIntegrityError",
    "SnapshotRef",
    "TodoItem",
    "TodoState",
    "WorkspaceCacheError",
    "WorkspaceCacheRoot",
    "WorkspaceMetadata",
    "resolve_session_cache",
]
