"""Request boundary that serializes destructive clears against memory API work."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request

from .dependencies import _resolve_unified_memory


async def memory_operation_boundary(request: Request) -> AsyncIterator[None]:
    """Hold the shared memory-operation guard for every route except clear itself."""
    route = request.scope.get("route")
    route_path = str(getattr(route, "path", ""))
    if (
        request.method == "DELETE" and route_path.rstrip("/").endswith("/clear")
    ) or "/portability/" in route_path:
        yield
        return

    unified_memory = _resolve_unified_memory()
    if unified_memory is None:
        yield
        return

    async with unified_memory.memory_operation_guard():
        yield


__all__ = ["memory_operation_boundary"]
