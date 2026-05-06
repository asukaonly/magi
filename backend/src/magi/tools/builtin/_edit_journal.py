"""Snapshot-and-record helper used by mutating file tools.

P0.4 ships rollback by hooking the existing mutating tools (``file_edit``,
overwriting ``file_write``). Each mutation writes the *previous* bytes to a
content-addressed snapshot in the session cache and appends an ``EditRecord``
linking ``path -> snapshot``. The ``file_rollback`` tool walks the records
in reverse to restore.

The helpers here mirror ``_read_constraint`` in their degrade-gracefully
posture: if the session cache is unavailable, missing, or rejects the path,
the mutation still proceeds — auditing is a safety overlay, not a barrier.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...agent.workspace_cache import (
    EditOp,
    SessionCache,
    SnapshotRef,
    resolve_session_cache,
)
from ...core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SnapshotContext:
    """Captured state of a file before a mutation."""

    sha256_before: str
    snapshot_ref: SnapshotRef
    session_cache: SessionCache


def _resolve_session_cache(context: Any) -> SessionCache | None:
    env_vars = getattr(context, "env_vars", None) or {}
    sid = str(env_vars.get("session_id") or "").strip()
    if not sid:
        return None
    workspace = getattr(context, "workspace", None)
    if not workspace:
        return None
    try:
        return resolve_session_cache(workspace, sid)
    except Exception:
        logger.warning("edit_journal.cache_init_failed", exc_info=True)
        return None


def _within_workspace(workspace: str, file_path: str) -> bool:
    try:
        Path(file_path).resolve().relative_to(Path(workspace).resolve())
        return True
    except ValueError:
        return False


def snapshot_before_edit(context: Any, file_path: str) -> SnapshotContext | None:
    """Capture the file's bytes into the session cache.

    Returns ``None`` when there is no active session, the file does not
    exist, the path is outside the workspace, or any underlying I/O / cache
    operation fails. The mutating tool then proceeds without an audit entry.
    """
    sc = _resolve_session_cache(context)
    if sc is None:
        return None
    workspace = getattr(context, "workspace", None) or ""
    if not _within_workspace(workspace, file_path):
        return None
    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except Exception:
        logger.warning("edit_journal.read_failed", exc_info=True)
        return None
    try:
        ref = sc.write_snapshot(data)
    except Exception:
        logger.warning("edit_journal.snapshot_failed", exc_info=True)
        return None
    return SnapshotContext(
        sha256_before=hashlib.sha256(data).hexdigest(),
        snapshot_ref=ref,
        session_cache=sc,
    )


def record_edit_after(
    context: Any,
    file_path: str,
    snapshot: SnapshotContext | None,
    *,
    op: EditOp,
) -> None:
    """Record an ``EditRecord`` after a successful mutation. No-op on failure."""
    _ = context
    if snapshot is None:
        return
    path = Path(file_path)
    try:
        after_bytes = path.read_bytes() if path.is_file() else b""
    except Exception:
        logger.warning("edit_journal.read_after_failed", exc_info=True)
        return
    sha_after = hashlib.sha256(after_bytes).hexdigest()
    try:
        snapshot.session_cache.record_edit(
            path=file_path,
            op=op,
            sha256_before=snapshot.sha256_before,
            sha256_after=sha_after,
            snapshot_ref=snapshot.snapshot_ref.sha256,
        )
    except Exception:
        logger.warning("edit_journal.record_failed", exc_info=True)
