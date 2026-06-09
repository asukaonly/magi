"""Read-before-edit constraint shared by file_read / file_edit / file_write.

The helpers here are intentionally narrow:

* ``record_read_in_session`` - call after a successful ``file_read``. Stores
  a ``ReadRecord`` (path + sha256 + size + line_count + mtime) in the session
  cache so that subsequent edits can verify the file was inspected.
* ``require_prior_read`` - call before any mutation of an existing file.
  Returns a human-readable error string the caller can put on a ``ToolResult``
  when the constraint blocks, or ``None`` when the mutation is allowed.

Both helpers degrade gracefully:

* If the context has no ``session_id``, the constraint is disabled. Some
  callers (cron, bootstrap) execute file tools without a chat session and
  must not be locked out.
* If the workspace cache fails to initialize (disk full, permissions, etc.),
  we fall through and allow the operation. The constraint is a safety overlay;
  it must not break the underlying file ops when its own infrastructure is
  broken.
"""
from __future__ import annotations

from typing import Any

from magi_plugin_sdk.workspace_cache import SessionCache, resolve_session_cache
from ...core.logger import get_logger

logger = get_logger(__name__)


_BLOCK_TEMPLATE = (
    "Refusing to modify {path!r} because it has not been read in this session "
    "(or its content has changed since the last read). Call file_read on this "
    "path first, then retry the edit."
)


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
        logger.warning("read_constraint.cache_init_failed", exc_info=True)
        return None


def record_read_in_session(context: Any, file_path: str) -> None:
    """Record a successful read into the session cache, never raising."""
    sc = _resolve_session_cache(context)
    if sc is None:
        return
    try:
        sc.record_read(file_path)
    except Exception:
        logger.debug("read_constraint.record_failed", exc_info=True)


def require_prior_read(context: Any, file_path: str) -> str | None:
    """Return a block message when the edit must be refused, else ``None``."""
    sc = _resolve_session_cache(context)
    if sc is None:
        return None
    try:
        if sc.has_read(file_path):
            return None
    except Exception:
        logger.warning("read_constraint.has_read_failed", exc_info=True)
        return None
    return _BLOCK_TEMPLATE.format(path=file_path)
