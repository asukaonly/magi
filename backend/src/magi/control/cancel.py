"""Async cancellation signal for long-running agent runs.

This module defines :class:`CancelToken`, the single cooperative abort
protocol used across the agent runtime. Historically the chat path
threaded a ``Callable[[], bool]`` ``cancel_checker`` through
``FunctionCallingOrchestrator``; the background-task runtime needs a
richer signal (asyncio.Event + observable reason), so both surfaces now
agree on this protocol.

Design notes:

* ``is_cancelled`` is ``async`` so implementations may ``await`` on an
  :class:`asyncio.Event`, look up coordinator state, or perform any
  other coroutine-friendly check without blocking the event loop.
* ``reason`` is best-effort metadata surfaced to callers after
  cancellation (e.g. ``"user_interrupt"``, ``"backend_restart"``).
  It is ``None`` until a cancellation has actually been observed.
* :func:`null_cancel_token` removes the ``None``-check boilerplate from
  the orchestrator: callers that do not care about cancellation pass
  the noop token and the probe always returns ``False``.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

__all__ = [
    "CancelToken",
    "CancelReason",
    "NullCancelToken",
    "EventCancelToken",
    "SessionRunCancelToken",
    "null_cancel_token",
]


CancelReason = str


@runtime_checkable
class CancelToken(Protocol):
    """Cooperative cancellation signal polled by long-running runs."""

    async def is_cancelled(self) -> bool:  # pragma: no cover - protocol
        """Return ``True`` once cancellation has been requested."""
        ...

    @property
    def reason(self) -> CancelReason | None:  # pragma: no cover - protocol
        """Best-effort label describing *why* cancellation occurred."""
        ...

    async def wait(self) -> None:  # pragma: no cover - protocol
        """Block until cancellation is requested."""
        ...


class NullCancelToken:
    """A token that is never cancelled.

    Use this wherever cancellation is not applicable to avoid sprinkling
    ``if token is not None`` checks through the orchestrator code paths.
    """

    __slots__ = ()

    async def is_cancelled(self) -> bool:
        return False

    @property
    def reason(self) -> CancelReason | None:
        return None

    async def wait(self) -> None:
        await asyncio.Event().wait()


_NULL_CANCEL_TOKEN = NullCancelToken()


def null_cancel_token() -> CancelToken:
    """Return the process-wide noop token singleton."""
    return _NULL_CANCEL_TOKEN


class EventCancelToken:
    """A CancelToken backed by an :class:`asyncio.Event`.

    Suitable for background-task workers where the manager flips an
    event to request cancellation. ``cancel(reason=...)`` records the
    reason and sets the event atomically.
    """

    __slots__ = ("_event", "_reason")

    def __init__(self, event: asyncio.Event | None = None) -> None:
        self._event = event if event is not None else asyncio.Event()
        self._reason: CancelReason | None = None

    async def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> CancelReason | None:
        return self._reason

    def cancel(self, reason: CancelReason = "cancelled") -> None:
        """Request cancellation. Idempotent — later reasons are ignored."""
        if self._event.is_set():
            return
        self._reason = reason
        self._event.set()

    async def wait(self) -> None:
        """Block until cancellation is requested."""
        await self._event.wait()


class SessionRunCancelToken:
    """A CancelToken bound to a single ``(session_id, run_id, revision)``.

    Mirrors the semantics of the former ``_build_cancel_checker`` callable:
    returns ``True`` only when
    :meth:`SessionRunCoordinator.get_run_status` reports the *exact* run
    we were bound to is ``cancelling`` or ``cancelled``. In every other
    case (superseded revision, replaced run_id, cleared active run) it
    returns ``False`` so the old tool-loop is allowed to finish naturally
    and its result is later flagged stale by
    :meth:`SessionRunCoordinator.record_result`.
    """

    __slots__ = (
        "_coordinator",
        "_session_id",
        "_run_id",
        "_revision",
        "_reason",
        "_event",
    )

    _CANCEL_STATUSES: frozenset[str] = frozenset({"cancelling", "cancelled"})

    def __init__(
        self,
        *,
        coordinator: object,
        session_id: str,
        run_id: str,
        revision: int,
    ) -> None:
        self._coordinator = coordinator
        self._session_id = session_id
        self._run_id = run_id
        self._revision = int(revision)
        self._reason: CancelReason | None = None
        self._event = asyncio.Event()

    def cancel(self, reason: CancelReason = "cancelled") -> None:
        """Latch cancellation independently of process-local run cleanup."""

        if self._event.is_set():
            return
        self._reason = str(reason or "cancelled")
        self._event.set()

    async def is_cancelled(self) -> bool:
        if self._event.is_set():
            return True
        status = self._coordinator.get_run_status(  # type: ignore[attr-defined]
            session_id=self._session_id,
            run_id=self._run_id,
            revision=self._revision,
        )
        if status in self._CANCEL_STATUSES:
            self.cancel(f"session_run_{status}")
            return True
        return False

    @property
    def reason(self) -> CancelReason | None:
        return self._reason

    async def wait(self) -> None:
        while not await self.is_cancelled():
            try:
                await asyncio.wait_for(self._event.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                continue
