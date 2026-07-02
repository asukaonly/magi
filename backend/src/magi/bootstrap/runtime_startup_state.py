"""Process-local runtime startup state shared by readiness flows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Literal

RuntimeStartupState = Literal["offline", "starting", "deferred", "ready", "failed", "stopping"]


@dataclass(frozen=True, slots=True)
class RuntimeStartupSnapshot:
    """Immutable snapshot of the current runtime startup state."""

    startup_state: RuntimeStartupState = "offline"
    reason: str | None = None
    detail: str | None = None
    updated_at_ms: int = 0


_lock = Lock()
_snapshot = RuntimeStartupSnapshot(updated_at_ms=int(time.time() * 1000))


def get_runtime_startup_snapshot() -> RuntimeStartupSnapshot:
    """Return the latest process-local runtime startup snapshot."""
    with _lock:
        return _snapshot


def set_runtime_startup_state(
    startup_state: RuntimeStartupState,
    *,
    reason: str | None = None,
    detail: str | None = None,
) -> RuntimeStartupSnapshot:
    """Replace the process-local runtime startup snapshot."""
    global _snapshot
    next_snapshot = RuntimeStartupSnapshot(
        startup_state=startup_state,
        reason=reason,
        detail=detail,
        updated_at_ms=int(time.time() * 1000),
    )
    with _lock:
        _snapshot = next_snapshot
    return next_snapshot
