"""Re-export shim — canonical implementation in magi_plugin_sdk.workspace_cache."""
from magi_plugin_sdk.workspace_cache.contracts import *  # noqa: F401, F403
from magi_plugin_sdk.workspace_cache.contracts import (
    EditOp,
    EditRecord,
    ReadRecord,
    SCHEMA_VERSION,
    SnapshotRef,
    WorkspaceMetadata,
)

__all__ = [
    "EditOp",
    "EditRecord",
    "ReadRecord",
    "SCHEMA_VERSION",
    "SnapshotRef",
    "WorkspaceMetadata",
]
