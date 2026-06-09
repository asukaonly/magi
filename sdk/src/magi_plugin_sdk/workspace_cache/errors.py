"""Error types for the workspace cache."""
from __future__ import annotations


class WorkspaceCacheError(Exception):
    """Base error for workspace cache operations."""


class SnapshotIntegrityError(WorkspaceCacheError):
    """Raised when a snapshot's stored bytes do not match its expected hash."""


class SessionCacheCorruptError(WorkspaceCacheError):
    """Raised when a session cache file is malformed beyond recovery."""
