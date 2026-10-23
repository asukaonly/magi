"""Container-backed providers for runtime trace services."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..core.container import require_binding

if TYPE_CHECKING:
    from .store import RuntimeTraceStore




def resolve_runtime_trace_store() -> "RuntimeTraceStore":
    """Return the active runtime trace store binding."""
    return cast("RuntimeTraceStore", require_binding("runtime_trace_store"))
