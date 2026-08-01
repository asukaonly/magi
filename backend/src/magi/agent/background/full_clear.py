"""Clear-only owner for background-task persistence during crash recovery."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class BackgroundTaskFullClearOwner:
    """Expose only the operations needed by the global data-clear transaction.

    A restarted backend must be able to erase durable background-task history
    without starting the normal dispatcher or rehydrating pending work. This
    owner deliberately has no execution API.
    """

    def __init__(self, *, store: Any) -> None:
        self._store = store
        self._boundary_lock = asyncio.Lock()
        self._boundary_active = False

    @property
    def store(self) -> Any:
        """Return the underlying persistence store for diagnostics/tests."""

        return self._store

    async def start(self) -> None:
        """Initialize persistence without recovering or dispatching old work."""

        await self._store.initialize()

    async def stop(self) -> None:
        """Stop the clear-only owner; no worker was started."""

        return None

    @asynccontextmanager
    async def conversation_scope_boundary(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        origin_turn_ids: set[str] | None = None,
        task_ids: set[str] | None = None,
        pending_message_ids: set[str] | None = None,
        reason: str = "conversation_deleted",
        timeout_seconds: float = 30.0,
    ) -> AsyncIterator[None]:
        """Seal the global clear scope without admitting scoped operations."""

        del reason, timeout_seconds
        if any(
            value is not None
            for value in (
                user_id,
                session_id,
                origin_turn_ids,
                task_ids,
                pending_message_ids,
            )
        ):
            raise RuntimeError(
                "Full-clear recovery owner only supports the global conversation scope"
            )
        async with self._boundary_lock:
            self._boundary_active = True
            try:
                yield
            finally:
                self._boundary_active = False

    async def clear_all_history(self) -> dict[str, int]:
        """Erase all durable background-task content inside the global seal."""

        if not self._boundary_active:
            raise RuntimeError("Background task history clear requires a global admission seal")
        return await self._store.clear_all()


__all__ = ["BackgroundTaskFullClearOwner"]
