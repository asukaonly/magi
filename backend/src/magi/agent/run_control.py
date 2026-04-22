"""Runtime control primitives for long-running orchestrator runs.

This module complements :mod:`magi.agent.cancel` by providing two
cooperative signals that live *alongside* (not instead of) a cancel
token:

* :class:`SteerInbox` — a thread-safe FIFO queue of user-authored
  follow-up messages that the chat layer can push into an already
  running orchestrator loop. The orchestrator drains the inbox at each
  tool boundary and appends the contents to its message history before
  the next LLM call. This is the "steer" semantic pioneered by
  OpenClaw's command-queue and refined for Magi: interrupt-style
  supersede remains available for hard aborts, but routine mid-run
  clarifications ("use Python not JS", "also include 2023 data") no
  longer throw away the in-flight run.

* :class:`DetachSignal` — a one-shot flag the chat layer can set when
  the run should stop occupying the foreground chat turn and hand its
  message history over to a background worker. When the orchestrator
  observes it at a tool boundary, it returns a ``detached``
  :class:`ExecutionOutcome` carrying the full ``messages`` list. The
  chat post-processor then builds a :class:`BackgroundTaskSpec` seeded
  with those messages so the background executor can resume from the
  exact same LLM turn without re-running the work that was already
  completed.

Boundary choice
---------------
Both primitives are polled at the **top of each orchestrator iteration**
— i.e. after the previous iteration's tool batch has been executed and
its ``tool`` messages appended, but **before** the next LLM call. That
point is already the one where :class:`CancelToken` is polled, and it
is the only point in the loop where the full in-progress state
collapses to a serialisable ``messages: list[dict]``. Keeping all three
signals on the same boundary avoids partially-applied steers (e.g. a
message injected after the LLM chose tools but before the tool batch
ran) and rules out any need for coroutine-level checkpointing.

Thread/loop safety
------------------
Both classes are designed to be produced by one coroutine (the chat
handler) and consumed by another (the orchestrator loop), running on
the same event loop. Internal state is plain ``deque`` / ``bool`` with
an ``asyncio.Lock`` guarding :class:`SteerInbox` mutations so producers
and consumers can race without corruption. Neither primitive performs
any IO.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DetachRequested",
    "DetachSignal",
    "OrchestratorSnapshot",
    "SteerInbox",
    "SteerMessage",
    "SteerReason",
]


SteerReason = str


@dataclass(slots=True, frozen=True)
class SteerMessage:
    """A user-authored follow-up delivered to an in-flight run."""

    content: str
    reason: SteerReason = "follow_up"
    metadata: dict[str, Any] = field(default_factory=dict)


class SteerInbox:
    """FIFO queue of :class:`SteerMessage` entries awaiting injection.

    Producers call :meth:`push`; consumers call :meth:`drain` at each
    tool boundary and receive every message enqueued since the previous
    drain. The inbox does not block — draining an empty inbox returns
    an empty list synchronously.
    """

    __slots__ = ("_queue", "_lock")

    def __init__(self) -> None:
        self._queue: deque[SteerMessage] = deque()
        self._lock = asyncio.Lock()

    async def push(self, message: SteerMessage) -> None:
        """Enqueue ``message`` for the next drain."""
        async with self._lock:
            self._queue.append(message)

    async def drain(self) -> list[SteerMessage]:
        """Pop and return every pending message in FIFO order."""
        async with self._lock:
            if not self._queue:
                return []
            drained = list(self._queue)
            self._queue.clear()
            return drained

    def is_empty(self) -> bool:
        """Best-effort, lock-free emptiness probe (may race)."""
        return not self._queue


@dataclass(slots=True, frozen=True)
class DetachRequested:
    """Metadata describing why a detach was requested."""

    reason: SteerReason = "user_request"
    requested_by: str = "user"
    note: str = ""


class DetachSignal:
    """One-shot detach-request flag polled by the orchestrator.

    ``request`` is idempotent — subsequent calls keep the first
    :class:`DetachRequested` payload so a burst of requests does not
    overwrite the recorded reason. The orchestrator observes the flag
    at the next tool boundary and exits with a ``detached``
    :class:`ExecutionOutcome`.
    """

    __slots__ = ("_event", "_payload")

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._payload: DetachRequested | None = None

    def request(self, payload: DetachRequested | None = None) -> None:
        """Flag a detach request. Idempotent."""
        if self._event.is_set():
            return
        self._payload = payload or DetachRequested()
        self._event.set()

    def is_requested(self) -> bool:
        return self._event.is_set()

    @property
    def payload(self) -> DetachRequested | None:
        """Return the recorded request payload, or ``None``."""
        return self._payload

    async def wait(self) -> DetachRequested:
        """Block until detach is requested and return the payload."""
        await self._event.wait()
        # ``request`` sets ``_payload`` before setting the event, so the
        # payload is always non-None here.
        assert self._payload is not None
        return self._payload


@dataclass(slots=True, frozen=True)
class OrchestratorSnapshot:
    """Serialisable in-progress state captured at a tool boundary.

    Produced when the orchestrator observes a :class:`DetachSignal`
    request and exits with ``ExecutionOutcome.status == "detached"``.
    ``messages`` is a deep copy of the orchestrator's message history
    at that point; callers may therefore hand the snapshot to a
    background worker that continues from the same LLM turn.
    """

    messages: list[dict[str, Any]]
    iterations: int
    reason: SteerReason
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [dict(msg) for msg in self.messages],
            "iterations": int(self.iterations),
            "reason": str(self.reason),
            "note": str(self.note),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrchestratorSnapshot":
        return cls(
            messages=[dict(msg) for msg in (data.get("messages") or [])],
            iterations=int(data.get("iterations") or 0),
            reason=str(data.get("reason") or "detached"),
            note=str(data.get("note") or ""),
        )
