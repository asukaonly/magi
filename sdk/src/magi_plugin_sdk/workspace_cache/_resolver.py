"""Convenience resolver for session cache instances."""
from __future__ import annotations

from pathlib import Path

from .root import WorkspaceCacheRoot
from .session import SessionCache


def resolve_session_cache(workspace_root: str | Path, session_id: str) -> SessionCache:
    """Ensure cache structure exists and return a ``SessionCache`` for ``session_id``."""
    root = WorkspaceCacheRoot.ensure(workspace_root)
    sc = SessionCache(root=root, session_id=session_id)
    _ = sc.session_dir
    return sc
