"""Runtime control primitives for long-running orchestrator runs.

This module complements :mod:`magi.control.cancel` by providing two
cooperative signals that live *alongside* (not instead of) a cancel
token:

* :class:`RunInputInbox` — a thread-safe FIFO queue of user-authored
  follow-up messages that the chat layer can push into an already
  running orchestrator loop. The orchestrator drains the inbox at each
  safe step boundary and appends the contents to model history before
  the next LLM call. Routine mid-run clarifications ("use Python not
  JS", "also include 2023 data") therefore extend the current run
  without a separate semantic classifier.

* :class:`DetachSignal` — a one-shot flag the chat layer can set when
  the run should stop occupying the foreground chat turn and hand its
  message history over to a background worker. When the orchestrator
  observes it at a tool boundary, it returns a ``detached``
  :class:`ExecutionOutcome` carrying the full ``messages`` list. The
  chat post-processor then builds a :class:`BackgroundTaskSpec` seeded
  with those messages so the background executor can resume from the
  exact same LLM turn without re-running the work that was already
  completed.

* :class:`RunControl` — bundle of all five cooperative signals
  (``CancelToken``, ``DetachSignal``, ``RunInputInbox``, ``RetractSignal``,
  ``SuspendSignal``) passed as one parameter to every node in a run.
  Construct with :func:`null_run_control` for tests / default callers.

Boundary choice
---------------
Both primitives are polled at the **top of each orchestrator iteration**
— i.e. after the previous iteration's tool batch has been executed and
its ``tool`` messages appended, but **before** the next LLM call. That
point is already the one where :class:`CancelToken` is polled, and it
is the only point in the loop where the full in-progress state
collapses to a serialisable ``messages: list[dict]``. Keeping all three
signals on the same boundary avoids partially-applied inputs (e.g. a
message injected after the LLM chose tools but before the tool batch
ran) and rules out any need for coroutine-level checkpointing.

Thread/loop safety
------------------
Both classes are designed to be produced by one coroutine (the chat
handler) and consumed by another (the orchestrator loop), running on
the same event loop. Internal state is plain ``deque`` / ``bool`` with
an ``asyncio.Lock`` guarding :class:`RunInputInbox` mutations so producers
and consumers can race without corruption. Neither primitive performs
any IO.
"""

from __future__ import annotations

import asyncio
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from magi.control.cancel import CancelToken

__all__ = [
    "DetachRequested",
    "DetachSignal",
    "RetractRequested",
    "RetractSignal",
    "RunControl",
    "ControlReason",
    "RunInputInbox",
    "RunInputMessage",
    "SuspendRequested",
    "SuspendSignal",
    "bind_detach_signal",
    "current_detach_signal",
    "null_run_control",
]


ControlReason = str


@dataclass(slots=True, frozen=True)
class RunInputMessage:
    """A user-authored follow-up delivered to an in-flight run."""

    content: str
    reason: ControlReason = "follow_up"
    metadata: dict[str, Any] = field(default_factory=dict)


class RunInputInbox:
    """FIFO queue of :class:`RunInputMessage` entries awaiting injection.

    Producers call :meth:`push`; consumers call :meth:`drain` at each
    tool boundary and receive every message enqueued since the previous
    drain. The inbox does not block — draining an empty inbox returns
    an empty list synchronously.
    """

    __slots__ = ("_queue", "_lock")

    def __init__(self) -> None:
        self._queue: deque[RunInputMessage] = deque()
        self._lock = asyncio.Lock()

    async def push(self, message: RunInputMessage) -> None:
        """Enqueue ``message`` for the next drain."""
        async with self._lock:
            self._queue.append(message)

    async def drain(self) -> list[RunInputMessage]:
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

    reason: ControlReason = "user_request"
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
class RetractRequested:
    """Metadata describing why a retract was requested.

    A retract is distinct from a cancel: it asks the run to stop AND
    requests that any partial output already delivered to a channel be
    rolled back. ``CancelToken`` leaves delivered partials in place;
    ``RetractSignal`` instructs the DeliveryRouter to undo them.
    """

    reason: ControlReason = "user_retract"
    requested_by: str = "user"
    note: str = ""


class RetractSignal:
    """One-shot retract-request flag polled by run nodes.

    Polled at the same boundary as :class:`CancelToken` and
    :class:`DetachSignal`. When set, the node returns a ``retracted``
    outcome and the kernel calls ``DeliveryRouter.fanout_retract`` on
    the receipts collected during the node's execution.

    ``request`` is idempotent — the first payload wins so cascading
    retract triggers do not overwrite the original reason.
    """

    __slots__ = ("_event", "_payload")

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._payload: RetractRequested | None = None

    def request(self, payload: RetractRequested | None = None) -> None:
        """Flag a retract request. Idempotent."""
        if self._event.is_set():
            return
        self._payload = payload or RetractRequested()
        self._event.set()

    def is_requested(self) -> bool:
        return self._event.is_set()

    @property
    def payload(self) -> RetractRequested | None:
        """Return the recorded request payload, or ``None``."""
        return self._payload

    async def wait(self) -> RetractRequested:
        """Block until retract is requested and return the payload."""
        await self._event.wait()
        assert self._payload is not None
        return self._payload


@dataclass(slots=True, frozen=True)
class SuspendRequested:
    """Metadata describing why a suspend was requested.

    A suspend is distinct from a detach: detach hands ownership to a
    background executor; suspend pauses the run in place expecting the
    user to reattach. Suspend is also unique in that it is *clearable*
    — when the user reattaches, the same RunControl can resume with
    ``clear()`` rather than constructing a fresh signal.
    """

    reason: ControlReason = "window_closed"
    requested_by: str = "user"
    note: str = ""


class SuspendSignal:
    """One-shot but clearable suspend-request flag.

    Polled at the same boundary as :class:`CancelToken`. When set, the
    node returns a ``suspended`` outcome and the kernel persists the
    snapshot in place. ``clear()`` resets the flag for resume.
    """

    __slots__ = ("_event", "_payload")

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._payload: SuspendRequested | None = None

    def request(self, payload: SuspendRequested | None = None) -> None:
        """Flag a suspend request. Idempotent."""
        if self._event.is_set():
            return
        self._payload = payload or SuspendRequested()
        self._event.set()

    def clear(self) -> None:
        """Reset the suspend flag. Used on resume to make the same
        RunControl reusable across a suspend/resume cycle."""
        self._event.clear()
        self._payload = None

    def is_requested(self) -> bool:
        return self._event.is_set()

    @property
    def payload(self) -> SuspendRequested | None:
        """Return the recorded request payload, or ``None``."""
        return self._payload

    async def wait(self) -> SuspendRequested:
        """Block until suspend is requested and return the payload."""
        await self._event.wait()
        # `request` sets `_payload` before setting the event; `clear()`
        # is only safe to call after the `wait()` consumer has returned,
        # so on this line `_payload` is always set.
        assert self._payload is not None
        return self._payload


@dataclass(slots=True)
class RunControl:
    """Bundle of cooperative control signals shared by every node in a run.

    Polled together at one boundary (top of node iteration, after
    previous tool batch appended, before next LLM call). Keeping a single
    bundle instead of five separate parameters means new signals can be
    added without re-threading every node/handler signature.

    The fields are *not* frozen because some signals (``SuspendSignal``)
    are clearable. The bundle itself is constructed once per run and
    shared by reference; concurrent producers/consumers coordinate via
    each individual signal's internal lock.

    All callers must run on the same asyncio event loop; the bundle does
    not provide cross-loop synchronization beyond what each individual
    signal already enforces.
    """

    cancel_token: "CancelToken"
    detach_signal: DetachSignal
    retract_signal: RetractSignal
    suspend_signal: SuspendSignal
    input_queue: RunInputInbox


def null_run_control() -> RunControl:
    """Return a RunControl whose every signal is a no-op.

    Useful for tests, for callers that do not need control, and as a
    safe default for handler signatures during the Phase A migration
    while existing call sites are updated.
    """
    from magi.control.cancel import null_cancel_token

    return RunControl(
        cancel_token=null_cancel_token(),
        detach_signal=DetachSignal(),
        retract_signal=RetractSignal(),
        suspend_signal=SuspendSignal(),
        input_queue=RunInputInbox(),
    )


# ---------------------------------------------------------------------
# ContextVar bridge for builtin tools
# ---------------------------------------------------------------------
#
# Tools do not receive the orchestrator's DetachSignal as a direct
# parameter (ToolExecutionContext is product-agnostic and must not
# leak orchestration internals). Instead the orchestrator binds the
# active signal into this ContextVar for the duration of
# the unified run entry; the ``detach_to_background`` builtin tool
# reads it to flag a detach request. Tools running outside an
# orchestrator loop see ``None`` and can report "not supported here".

_current_detach_signal: ContextVar[DetachSignal | None] = ContextVar(
    "magi_current_detach_signal", default=None
)


def current_detach_signal() -> DetachSignal | None:
    """Return the :class:`DetachSignal` active on this coroutine, or
    ``None`` if none is bound. Safe to call from any code path."""
    return _current_detach_signal.get()


class bind_detach_signal:
    """Context manager that binds ``signal`` as the active detach
    signal for the duration of a ``with`` block.

    Use as ``with bind_detach_signal(signal): ...``. The ContextVar is
    restored on exit, whether the block raised or returned normally.
    Passing ``None`` is a no-op context manager (preserving any outer
    binding).
    """

    __slots__ = ("_signal", "_token")

    def __init__(self, signal: DetachSignal | None) -> None:
        self._signal = signal
        self._token: Any = None

    def __enter__(self) -> DetachSignal | None:
        if self._signal is not None:
            self._token = _current_detach_signal.set(self._signal)
        return self._signal

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._token is not None:
            _current_detach_signal.reset(self._token)
            self._token = None
