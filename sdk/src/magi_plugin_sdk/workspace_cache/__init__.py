"""Session-scoped workspace cache under ``<workspace_root>/.magi/``."""
from .contracts import (
    EditOp,
    EditRecord,
    ReadRecord,
    SCHEMA_VERSION,
    SnapshotRef,
    TodoItem,
    TodoState,
    WorkspaceMetadata,
)
from .errors import (
    SessionCacheCorruptError,
    SnapshotIntegrityError,
    WorkspaceCacheError,
)
from .root import WorkspaceCacheRoot
from .session import SessionCache
from ._resolver import resolve_session_cache

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
