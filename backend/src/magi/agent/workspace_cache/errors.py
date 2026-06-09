"""Re-export shim — canonical implementation in magi_plugin_sdk.workspace_cache."""
from magi_plugin_sdk.workspace_cache.errors import *  # noqa: F401, F403
from magi_plugin_sdk.workspace_cache.errors import (
    WorkspaceCacheError,
    SnapshotIntegrityError,
    SessionCacheCorruptError,
)

__all__ = [
    "WorkspaceCacheError",
    "SnapshotIntegrityError",
    "SessionCacheCorruptError",
]
