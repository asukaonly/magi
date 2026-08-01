"""TTL cache for `MCPManager.read_resource` results.

The chat send pipeline reads an attached resource at send time and inlines
the result into the prompt. The same resource may be referenced by the
`@`-picker (preview/peek), then again by the eventual send — caching the
read for ~60s avoids paying the round-trip twice in normal use.

Cache invariants:
- Keyed by ``(server_id, uri)``.
- Each entry has a wall-clock expiry. Stale entries are evicted lazily.
- Concurrent reads of the same key share a single in-flight ``read_resource``
  call (deduped via per-key asyncio.Lock).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from ..core.operation_barrier import AsyncOperationBarrier

DEFAULT_TTL_SECONDS = 60.0


class MCPResourceCacheClearedError(RuntimeError):
    """Raised when a resource read crossed a full local-data clear."""


class MCPResourceCache:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = float(ttl_seconds)
        self._entries: dict[tuple[str, str], tuple[float, Any]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._clear_barrier = AsyncOperationBarrier()
        self._clear_generation = 0

    def get(self, server_id: str, uri: str) -> Any | None:
        key = (server_id, uri)
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            self._entries.pop(key, None)
            return None
        return value

    def put(self, server_id: str, uri: str, value: Any) -> None:
        self._entries[(server_id, uri)] = (
            time.monotonic() + self._ttl,
            value,
        )

    def invalidate(self, server_id: str, uri: str) -> None:
        self._entries.pop((server_id, uri), None)

    def clear(self) -> None:
        self._clear_generation += 1
        self._entries.clear()
        self._locks.clear()

    @asynccontextmanager
    async def global_data_clear_boundary(self) -> AsyncIterator[None]:
        """Drain active reads and reject reads queued across a data clear."""
        async with self._clear_barrier.exclusive():
            self.clear()
            try:
                yield
            finally:
                self.clear()

    async def get_or_fetch(
        self,
        server_id: str,
        uri: str,
        fetch: Callable[[str, str], Awaitable[Any]],
    ) -> Any:
        expected_generation = self._clear_generation
        async with self._clear_barrier.operation():
            if expected_generation != self._clear_generation:
                raise MCPResourceCacheClearedError(
                    "MCP resource read was cancelled by a local data clear"
                )
            cached = self.get(server_id, uri)
            if cached is not None:
                return cached

            async with self._global_lock:
                lock = self._locks.setdefault((server_id, uri), asyncio.Lock())

            async with lock:
                cached = self.get(server_id, uri)
                if cached is not None:
                    return cached
                value = await fetch(server_id, uri)
                if expected_generation != self._clear_generation:
                    raise MCPResourceCacheClearedError(
                        "MCP resource read was cancelled by a local data clear"
                    )
                self.put(server_id, uri, value)
                return value


_default_cache: MCPResourceCache | None = None


def get_default_cache() -> MCPResourceCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = MCPResourceCache()
    return _default_cache
