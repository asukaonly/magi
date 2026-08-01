"""Generic async broker for suspend-then-resolve interactions.

The control plane repeatedly needs the same pattern:

1. Agent/orchestrator produces a *request* (``PermissionRequest``,
   ``AskRequest``, ``PlanSession``).
2. The request id is handed to the frontend / another actor.
3. The agent coroutine then awaits the matching *response* with an
   optional timeout.
4. When the response arrives (via IPC, API, another coroutine) the
   awaiter is woken up; on timeout a sentinel is raised instead.

This module factors that pattern out so ``permission/``, ``ask/`` and
``plan/`` share one battle-tested primitive instead of each rolling
their own ``asyncio.Event`` plumbing.

Design notes
------------

* The broker is **not** a persistence layer. Callers are responsible
  for durability (writing to L0 / SQLite / event log) if the host
  process can crash while an interaction is pending.
* ``resolve`` is idempotent on the winning side only: the first
  resolution wins, later resolutions are dropped and logged.
* ``close`` cancels every pending interaction with
  :class:`InteractionClosedError`; used at shutdown / session teardown
  to avoid leaking coroutines waiting on a future that will never
  arrive.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import structlog

__all__ = [
    "InteractionBroker",
    "InteractionClosedError",
    "InteractionTimeoutError",
    "PendingInteraction",
]


logger = structlog.get_logger(__name__)


ResponseT = TypeVar("ResponseT")


class InteractionTimeoutError(asyncio.TimeoutError):
    """Raised by :meth:`InteractionBroker.wait` when the deadline elapses."""

    def __init__(self, interaction_id: str, *, kind: str) -> None:
        super().__init__(f"interaction {kind}:{interaction_id} timed out")
        self.interaction_id = interaction_id
        self.kind = kind


class InteractionClosedError(RuntimeError):
    """Raised when the broker is shut down with pending waiters."""

    def __init__(self, interaction_id: str, *, kind: str, reason: str) -> None:
        super().__init__(
            f"interaction {kind}:{interaction_id} closed before resolution: {reason}"
        )
        self.interaction_id = interaction_id
        self.kind = kind
        self.reason = reason


@dataclass(slots=True)
class PendingInteraction(Generic[ResponseT]):
    """State for one outstanding interaction awaiting a response."""

    interaction_id: str
    kind: str
    future: asyncio.Future[ResponseT]
    metadata: dict[str, Any] = field(default_factory=dict)


class InteractionBroker:
    """Suspend a coroutine until an external party resolves the request.

    Typical usage from the producer side:

    .. code-block:: python

        broker = InteractionBroker()
        # ... publish the request payload over IPC ...
        try:
            response = await broker.wait(
                interaction_id="abc",
                kind="permission",
                timeout_seconds=120,
            )
        except InteractionTimeoutError:
            response = default_on_timeout()

    The resolver side (IPC handler, UI callback) calls
    :meth:`resolve` with the same ``interaction_id``.

    The broker is scoped per-kind on the ID space: two different kinds
    may share an id without conflict, which makes it safe for
    permission/ask/plan to coexist.
    """

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingInteraction[Any]] = {}
        self._closed: bool = False
        self._lock = asyncio.Lock()
        self._clear_generation = 0
        self._clear_request_count = 0

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Reject pending interactions and seal the broker during a full clear."""
        self._clear_request_count += 1
        self._clear_generation += 1
        try:
            async with self._lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for item in pending:
                if not item.future.done():
                    item.future.set_exception(
                        InteractionClosedError(
                            item.interaction_id,
                            kind=item.kind,
                            reason="user_content_cleared",
                        )
                    )
            yield
        finally:
            self._clear_request_count -= 1

    def user_content_generation(self) -> int:
        """Return the generation a new logical interaction must retain."""
        return self._clear_generation

    # ------------------------------------------------------------------
    # Waiter side
    # ------------------------------------------------------------------

    async def wait(
        self,
        *,
        interaction_id: str,
        kind: str,
        timeout_seconds: float | None,
        metadata: dict[str, Any] | None = None,
        expected_generation: int | None = None,
    ) -> Any:
        """Suspend until :meth:`resolve` is called for the same key.

        Raises:
            InteractionTimeoutError: deadline elapsed.
            InteractionClosedError: broker was closed while waiting.
        """
        generation = (
            self._clear_generation
            if expected_generation is None
            else int(expected_generation)
        )
        if self._closed:
            raise InteractionClosedError(
                interaction_id, kind=kind, reason="broker_closed_on_enter"
            )
        if self._clear_request_count > 0:
            raise InteractionClosedError(
                interaction_id,
                kind=kind,
                reason="user_content_cleared",
            )
        key = (kind, interaction_id)
        async with self._lock:
            if self._closed:
                raise InteractionClosedError(
                    interaction_id,
                    kind=kind,
                    reason="broker_closed_on_enter",
                )
            if (
                self._clear_request_count > 0
                or generation != self._clear_generation
            ):
                raise InteractionClosedError(
                    interaction_id,
                    kind=kind,
                    reason="user_content_cleared",
                )
            if key in self._pending:
                raise RuntimeError(
                    f"interaction {kind}:{interaction_id} already pending"
                )
            future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
            pending = PendingInteraction(
                interaction_id=interaction_id,
                kind=kind,
                future=future,
                metadata=dict(metadata or {}),
            )
            self._pending[key] = pending
        try:
            if timeout_seconds is None:
                return await future
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise InteractionTimeoutError(interaction_id, kind=kind) from exc
        finally:
            async with self._lock:
                if self._pending.get(key) is pending:
                    self._pending.pop(key, None)

    # ------------------------------------------------------------------
    # Resolver side
    # ------------------------------------------------------------------

    async def resolve(
        self,
        *,
        interaction_id: str,
        kind: str,
        response: Any,
    ) -> bool:
        """Deliver ``response`` to the waiter for ``(kind, interaction_id)``.

        Returns ``True`` if a waiter was woken up, ``False`` if no
        matching interaction was pending (late/duplicate resolution).
        """
        async with self._lock:
            if self._clear_request_count > 0:
                return False
            pending = self._pending.get((kind, interaction_id))
            if pending is None:
                logger.debug(
                    "interaction_broker.resolve.miss",
                    kind=kind,
                    interaction_id=interaction_id,
                )
                return False
            if pending.future.done():
                return False
            pending.future.set_result(response)
            return True

    async def cancel(
        self,
        *,
        interaction_id: str,
        kind: str,
        reason: str = "cancelled",
    ) -> bool:
        """Cancel a pending interaction with :class:`InteractionClosedError`."""
        async with self._lock:
            if self._clear_request_count > 0:
                return False
            pending = self._pending.get((kind, interaction_id))
            if pending is None or pending.future.done():
                return False
            pending.future.set_exception(
                InteractionClosedError(interaction_id, kind=kind, reason=reason)
            )
            return True

    async def get_pending_metadata(
        self,
        *,
        interaction_id: str,
        kind: str,
    ) -> dict[str, Any] | None:
        """Return an isolated snapshot of one pending interaction's metadata."""

        async with self._lock:
            if self._clear_request_count > 0:
                return None
            pending = self._pending.get((kind, interaction_id))
            if pending is None or pending.future.done():
                return None
            return dict(pending.metadata)

    # ------------------------------------------------------------------
    # Introspection & shutdown
    # ------------------------------------------------------------------

    def pending_count(self) -> int:
        if self._clear_request_count > 0:
            return 0
        return len(self._pending)

    def list_pending(self) -> list[PendingInteraction[Any]]:
        if self._clear_request_count > 0:
            return []
        return list(self._pending.values())

    async def close(self, *, reason: str = "broker_closed") -> None:
        """Reject all pending interactions and prevent new ones."""
        async with self._lock:
            self._closed = True
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            if not item.future.done():
                item.future.set_exception(
                    InteractionClosedError(
                        item.interaction_id, kind=item.kind, reason=reason
                    )
                )
