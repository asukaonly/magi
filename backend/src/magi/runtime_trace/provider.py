"""Container-backed providers for runtime trace services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from .store import RuntimeTraceStore


def _require_runtime_trace_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def resolve_runtime_trace_store() -> "RuntimeTraceStore":
    """Return the active runtime trace store binding."""
    return cast("RuntimeTraceStore", _require_runtime_trace_binding("runtime_trace_store"))
