"""Session-scoped workspace cache under ``<workspace_root>/.magi/``."""
from .contracts import (
    EditOp,
    EditRecord,
    ReadRecord,
    SCHEMA_VERSION,
    SnapshotRef,
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
    "WorkspaceCacheError",
    "WorkspaceCacheRoot",
    "WorkspaceMetadata",
    "resolve_session_cache",
]
