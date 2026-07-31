"""In-memory access to user-controlled diagnostic logging policy."""

from __future__ import annotations

from threading import RLock

_POLICY_LOCK = RLock()
_FULL_CONTENT_LOGGING_ENABLED = True


def set_full_content_logging_enabled(enabled: bool) -> None:
    """Refresh the process-wide content policy after configuration loading."""
    global _FULL_CONTENT_LOGGING_ENABLED
    with _POLICY_LOCK:
        _FULL_CONTENT_LOGGING_ENABLED = bool(enabled)


def full_content_logging_enabled() -> bool:
    """Return the current full-content logging preference without file I/O."""
    with _POLICY_LOCK:
        return _FULL_CONTENT_LOGGING_ENABLED


__all__ = [
    "full_content_logging_enabled",
    "set_full_content_logging_enabled",
]
