"""Session-scoped batching for post-turn L0 attention updates."""

from __future__ import annotations

import asyncio
from itertools import islice
import logging
import math
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ATTENTION_UPDATE_TURN_THRESHOLD = 3
DEFAULT_ATTENTION_UPDATE_IDLE_SECONDS = 30.0
DEFAULT_ATTENTION_UPDATE_MAX_DELAY_SECONDS = 90.0
DEFAULT_RETRY_INITIAL_SECONDS = 1.0
DEFAULT_RETRY_MAX_SECONDS = 30.0
DEFAULT_CONFIG_POLL_INTERVAL_SECONDS = 0.25
DEFAULT_PROCESSED_TURN_DEDUPE_LIMIT = 1024
DEFAULT_MAX_BATCH_TURNS = 20
DEFAULT_MAX_PENDING_TURNS_PER_SESSION = 60
DEFAULT_MAX_BATCH_ATTEMPTS = 3

_IMMEDIATE_FACT_KINDS = frozenset(
    {
        "worker_update",
        "explore_task_completed",
    }
)
_IMMEDIATE_MESSAGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:^|[\s，,。.!！?？])(?:更正|纠正)(?:一下)?(?:[\s:：，,]|$)",
        r"(?:我(?:刚才)?说错了|准确地说|应该改成)",
        r"(?:不对|不是这样)[\s，,。:：]*(?:应该|是|我指|我的意思)",
        r"不是.{1,80}(?:而是|是)",
        r"\b(?:correction|i mean|i meant|what i meant was)\b",
        r"\bnot .{1,80}\b(?:but|rather)\b",
        r"(?:这个|该)?(?:话题|事情|问题).{0,12}(?:到此为止|结束|关闭)",
        r"(?:先)?不(?:用|要|再)?(?:聊|讨论|跟进)(?:这个|它)?",
        r"\b(?:drop|close|stop discussing|do not discuss|don't discuss)\b.{0,60}"
        r"\b(?:this|that|topic|issue)\b",
        r"(?:从现在开始|以后|今后|接下来).{0,80}"
        r"(?:必须|不要|不能|只|都要|一律|始终|请|回复|回答|称呼|叫我)",
        r"(?:请|你要)?记住.{0,80}(?:必须|不要|不能|只|始终)",
        r"(?:我保证|我承诺|我已经决定|就这么定|我们就按.{1,50}(?:来|做))",
        r"\b(?:from now on|going forward)\b.{0,100}"
        r"\b(?:must|always|never|only|do not|don't|keep|call|reply|respond|address)\b",
        r"\b(?:i promise|i have decided|i've decided|we agreed to|it's settled)\b",
    )
)


@dataclass(frozen=True, slots=True)
class AcceptedL0AttentionTurn:
    """One accepted, durably committed chat turn eligible for L0 analysis."""

    user_id: str
    session_id: str
    turn_id: str
    user_message: str
    assistant_response: str
    epoch: int
    accepted_at: float = field(default_factory=time.time)
    persona_id: str | None = None
    incoming_fact_kind: str | None = None
    execution_mode: str | None = None
    immediate: bool = False


AttentionBatch = tuple[AcceptedL0AttentionTurn, ...]
AttentionBatchProcessor = Callable[[AttentionBatch], Awaitable[bool]]
AttentionBatchFinalizer = Callable[[AttentionBatch], None]
AttentionConfigGetter = Callable[[], Any]
MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class _QueuedTurn:
    turn: AcceptedL0AttentionTurn
    enqueued_at: float


@dataclass(frozen=True, slots=True)
class _AttentionUpdatePolicy:
    turn_threshold: int
    idle_seconds: float
    max_delay_seconds: float


@dataclass(slots=True)
class _SessionState:
    pending: deque[_QueuedTurn] = field(default_factory=deque)
    pending_turn_ids: set[str] = field(default_factory=set)
    wake_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    latest_enqueue_at: float = 0.0
    retry_not_before: float = 0.0
    consecutive_failures: int = 0
    current_batch: tuple[_QueuedTurn, ...] = ()
    processing: bool = False
    force_flush: bool = False


class L0AttentionUpdateScheduler:
    """Batch accepted chat turns and process each session in order."""

    def __init__(
        self,
        *,
        processor: AttentionBatchProcessor,
        config_getter: AttentionConfigGetter,
        finalizer: AttentionBatchFinalizer | None = None,
        retry_initial_seconds: float = DEFAULT_RETRY_INITIAL_SECONDS,
        retry_max_seconds: float = DEFAULT_RETRY_MAX_SECONDS,
        config_poll_interval_seconds: float = DEFAULT_CONFIG_POLL_INTERVAL_SECONDS,
        processed_turn_dedupe_limit: int = DEFAULT_PROCESSED_TURN_DEDUPE_LIMIT,
        max_batch_turns: int = DEFAULT_MAX_BATCH_TURNS,
        max_pending_turns_per_session: int = DEFAULT_MAX_PENDING_TURNS_PER_SESSION,
        max_batch_attempts: int = DEFAULT_MAX_BATCH_ATTEMPTS,
        monotonic: MonotonicClock = time.monotonic,
    ) -> None:
        self._processor = processor
        self._config_getter = config_getter
        self._finalizer = finalizer
        self._retry_initial_seconds = max(0.0, float(retry_initial_seconds))
        self._retry_max_seconds = max(
            self._retry_initial_seconds,
            float(retry_max_seconds),
        )
        self._config_poll_interval_seconds = max(
            0.001,
            float(config_poll_interval_seconds),
        )
        self._processed_turn_dedupe_limit = max(1, int(processed_turn_dedupe_limit))
        self._max_batch_turns = min(
            DEFAULT_MAX_BATCH_TURNS,
            max(1, int(max_batch_turns)),
        )
        self._max_pending_turns_per_session = min(
            DEFAULT_MAX_PENDING_TURNS_PER_SESSION,
            max(
                self._max_batch_turns,
                int(max_pending_turns_per_session),
            ),
        )
        self._max_batch_attempts = min(
            DEFAULT_MAX_BATCH_ATTEMPTS,
            max(1, int(max_batch_attempts)),
        )
        self._monotonic = monotonic
        self._states: dict[str, _SessionState] = {}
        self._processed_turn_keys: set[tuple[str, str]] = set()
        self._processed_turn_order: deque[tuple[str, str]] = deque()
        self._lock = asyncio.Lock()
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self._closed = False

    async def enqueue(self, turn: AcceptedL0AttentionTurn) -> bool:
        """Queue one accepted turn unless its session/turn identity is invalid or known."""
        normalized = self._normalize_turn(turn)
        if normalized is None:
            return False

        async with self._lock:
            if self._closed:
                return False
            if (
                normalized.session_id,
                normalized.turn_id,
            ) in self._processed_turn_keys:
                return False
            state = self._states.get(normalized.session_id)
            if state is None:
                state = _SessionState()
                self._states[normalized.session_id] = state
            if normalized.turn_id in state.pending_turn_ids:
                return False

            if len(state.pending) >= self._max_pending_turns_per_session:
                dropped = self._drop_oldest_waiting_turn_locked(
                    normalized.session_id,
                    state,
                )
                if dropped is None:
                    self._remember_processed_turn_locked(
                        normalized.session_id,
                        normalized.turn_id,
                    )
                    self._finalize_turns((normalized,))
                    logger.warning(
                        "Dropped new L0 attention turn because only the in-flight batch remains",
                        extra={
                            "session_id": normalized.session_id,
                            "dropped_turn_id": normalized.turn_id,
                            "pending_limit": self._max_pending_turns_per_session,
                        },
                    )
                    return False
                logger.warning(
                    "Dropped queued L0 attention turn at session pending limit",
                    extra={
                        "session_id": normalized.session_id,
                        "dropped_turn_id": dropped.turn.turn_id,
                        "pending_limit": self._max_pending_turns_per_session,
                    },
                )

            now = self._monotonic()
            state.pending.append(_QueuedTurn(turn=normalized, enqueued_at=now))
            state.pending_turn_ids.add(normalized.turn_id)
            state.latest_enqueue_at = now
            self._idle_event.clear()
            self._ensure_session_worker_locked(normalized.session_id, state)
            state.wake_event.set()
            return True

    async def wait_idle(self, *, timeout_seconds: float | None = None) -> bool:
        """Wait until queued work succeeds or reaches a bounded drop outcome."""
        waiter = self._idle_event.wait()
        try:
            if timeout_seconds is None:
                await waiter
            else:
                await asyncio.wait_for(waiter, timeout=max(0.0, timeout_seconds))
        except asyncio.TimeoutError:
            return False
        return True

    def has_pending_work(self, session_id: str | None = None) -> bool:
        """Return whether accepted work is pending globally or for one session."""

        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return not self._idle_event.is_set()
        state = self._states.get(normalized_session_id)
        return bool(state is not None and (state.pending or state.processing))

    async def discard_session(self, session_id: str) -> None:
        """Cancel and discard queued analysis for one destructively cleared session."""

        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        async with self._lock:
            state = self._states.pop(normalized_session_id, None)
            if state is None:
                return
            task = state.task
            discarded = tuple(item.turn for item in state.pending)
            state.pending.clear()
            state.pending_turn_ids.clear()
            state.current_batch = ()
            state.processing = False
            self._refresh_idle_event_locked()
            self._finalize_turns(discarded)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def discard_turns(
        self,
        session_id: str,
        turn_ids: set[str] | frozenset[str],
    ) -> int:
        """Discard exact waiting turns without disturbing an in-flight prefix."""

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_ids = {
            str(turn_id or "").strip()
            for turn_id in turn_ids
            if str(turn_id or "").strip()
        }
        if not normalized_session_id or not normalized_turn_ids:
            return 0
        async with self._lock:
            state = self._states.get(normalized_session_id)
            if state is None:
                return 0
            protected_ids = {
                item.turn.turn_id
                for item in state.current_batch
            }
            discarded_entries = tuple(
                item
                for item in state.pending
                if item.turn.turn_id in normalized_turn_ids
                and item.turn.turn_id not in protected_ids
            )
            if not discarded_entries:
                return 0
            discarded_set = set(discarded_entries)
            state.pending = deque(
                item
                for item in state.pending
                if item not in discarded_set
            )
            for item in discarded_entries:
                state.pending_turn_ids.discard(item.turn.turn_id)
                self._remember_processed_turn_locked(
                    normalized_session_id,
                    item.turn.turn_id,
                )
            self._refresh_idle_event_locked()
            state.wake_event.set()
            self._finalize_turns(
                tuple(item.turn for item in discarded_entries)
            )
            return len(discarded_entries)

    async def shutdown(
        self,
        *,
        flush: bool = True,
        timeout_seconds: float | None = 5.0,
    ) -> bool:
        """Stop accepting turns and optionally flush all pending session batches."""
        async with self._lock:
            if self._closed and not self._states:
                return True
            self._closed = True
            if flush:
                for state in self._states.values():
                    if not state.pending:
                        continue
                    state.force_flush = True
                    state.retry_not_before = 0.0
                    state.wake_event.set()

        flushed = True
        if flush:
            flushed = await self.wait_idle(timeout_seconds=timeout_seconds)
        else:
            async with self._lock:
                flushed = not self._has_pending_work_locked()

        async with self._lock:
            tasks = [
                state.task
                for state in self._states.values()
                if state.task is not None and not state.task.done()
            ]
            discarded = tuple(
                item.turn
                for state in self._states.values()
                for item in state.pending
            )
            self._states.clear()
            self._idle_event.set()
            self._finalize_turns(discarded)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return flushed

    def _ensure_session_worker_locked(
        self,
        session_id: str,
        state: _SessionState,
    ) -> None:
        if state.task is not None and not state.task.done():
            return
        state.task = asyncio.create_task(
            self._run_session(session_id, state),
            name=f"l0-attention-update:{session_id}",
        )

    async def _run_session(self, session_id: str, state: _SessionState) -> None:
        try:
            while True:
                batch_entries, wait_seconds, should_exit = await self._next_action(
                    session_id,
                    state,
                )
                if should_exit:
                    return
                if batch_entries:
                    await self._process_batch(session_id, state, batch_entries)
                    continue
                await self._wait_for_wake(state, wait_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "L0 attention update session worker failed",
                extra={"session_id": session_id},
            )

    async def _next_action(
        self,
        session_id: str,
        state: _SessionState,
    ) -> tuple[tuple[_QueuedTurn, ...], float | None, bool]:
        async with self._lock:
            if not state.pending:
                if self._states.get(session_id) is state:
                    self._states.pop(session_id, None)
                self._refresh_idle_event_locked()
                return (), None, True

            now = self._monotonic()
            policy = self._current_policy()
            due = self._is_due(state, policy=policy, now=now)
            retry_blocked = state.retry_not_before > now
            if due and not retry_blocked and not state.processing:
                if not state.current_batch:
                    state.current_batch = tuple(islice(state.pending, self._max_batch_turns))
                state.processing = True
                state.force_flush = False
                return state.current_batch, None, False

            deadline = self._next_deadline(state, policy=policy, now=now)
            if retry_blocked:
                deadline = state.retry_not_before
            wait_seconds = max(0.0, deadline - now)
            wait_seconds = min(wait_seconds, self._config_poll_interval_seconds)
            state.wake_event.clear()
            return (), wait_seconds, False

    async def _process_batch(
        self,
        session_id: str,
        state: _SessionState,
        batch_entries: tuple[_QueuedTurn, ...],
    ) -> None:
        batch = tuple(item.turn for item in batch_entries)
        succeeded = False
        try:
            succeeded = bool(await self._processor(batch))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "L0 attention update batch processor failed",
                extra={
                    "session_id": session_id,
                    "turn_count": len(batch),
                },
            )

        async with self._lock:
            state.processing = False
            now = self._monotonic()
            if succeeded:
                self._remove_processed_prefix_locked(
                    session_id,
                    state,
                    batch_entries,
                )
                state.current_batch = ()
                state.consecutive_failures = 0
                state.retry_not_before = 0.0
                if self._closed and state.pending:
                    state.force_flush = True
            else:
                state.consecutive_failures += 1
                if state.consecutive_failures >= self._max_batch_attempts:
                    self._remove_processed_prefix_locked(
                        session_id,
                        state,
                        batch_entries,
                    )
                    logger.warning(
                        "Dropped L0 attention update batch after retry budget exhausted",
                        extra={
                            "session_id": session_id,
                            "turn_count": len(batch_entries),
                            "attempt_count": state.consecutive_failures,
                        },
                    )
                    state.current_batch = ()
                    state.consecutive_failures = 0
                    state.retry_not_before = 0.0
                    state.force_flush = bool(state.pending)
                else:
                    state.retry_not_before = now + self._retry_delay_seconds(
                        state.consecutive_failures
                    )
                    if self._closed:
                        state.force_flush = True
            self._refresh_idle_event_locked()
            state.wake_event.set()

    async def _wait_for_wake(
        self,
        state: _SessionState,
        wait_seconds: float | None,
    ) -> None:
        if wait_seconds is None:
            await state.wake_event.wait()
            return
        try:
            await asyncio.wait_for(
                state.wake_event.wait(),
                timeout=max(0.0, wait_seconds),
            )
        except asyncio.TimeoutError:
            return

    def _is_due(
        self,
        state: _SessionState,
        *,
        policy: _AttentionUpdatePolicy,
        now: float,
    ) -> bool:
        if state.current_batch:
            return True
        if state.force_flush:
            return True
        if any(item.turn.immediate for item in state.pending):
            return True
        if len(state.pending) >= policy.turn_threshold:
            return True
        return now >= self._next_deadline(state, policy=policy, now=now)

    @staticmethod
    def _next_deadline(
        state: _SessionState,
        *,
        policy: _AttentionUpdatePolicy,
        now: float,
    ) -> float:
        if not state.pending:
            return now
        oldest_deadline = state.pending[0].enqueued_at + policy.max_delay_seconds
        idle_deadline = state.latest_enqueue_at + policy.idle_seconds
        return min(oldest_deadline, idle_deadline)

    def _remove_processed_prefix_locked(
        self,
        session_id: str,
        state: _SessionState,
        batch_entries: tuple[_QueuedTurn, ...],
    ) -> None:
        finalized: list[AcceptedL0AttentionTurn] = []
        for expected in batch_entries:
            if not state.pending:
                break
            current = state.pending[0]
            if current is not expected:
                logger.error("L0 attention update queue prefix changed during processing")
                break
            state.pending.popleft()
            turn_id = current.turn.turn_id
            state.pending_turn_ids.discard(turn_id)
            self._remember_processed_turn_locked(session_id, turn_id)
            finalized.append(current.turn)
        self._finalize_turns(tuple(finalized))

    def _remember_processed_turn_locked(
        self,
        session_id: str,
        turn_id: str,
    ) -> None:
        key = (session_id, turn_id)
        if key in self._processed_turn_keys:
            return
        self._processed_turn_keys.add(key)
        self._processed_turn_order.append(key)
        while len(self._processed_turn_order) > self._processed_turn_dedupe_limit:
            expired = self._processed_turn_order.popleft()
            self._processed_turn_keys.discard(expired)

    def _drop_oldest_waiting_turn_locked(
        self,
        session_id: str,
        state: _SessionState,
    ) -> _QueuedTurn | None:
        """Drop stale queued work without changing an in-flight retry prefix."""

        protected_count = len(state.current_batch)
        if protected_count >= len(state.pending):
            return None
        drop_index = protected_count
        dropped = state.pending[drop_index]
        del state.pending[drop_index]
        state.pending_turn_ids.discard(dropped.turn.turn_id)
        self._remember_processed_turn_locked(
            session_id,
            dropped.turn.turn_id,
        )
        self._finalize_turns((dropped.turn,))
        return dropped

    def _finalize_turns(self, turns: AttentionBatch) -> None:
        if not turns or self._finalizer is None:
            return
        try:
            self._finalizer(turns)
        except Exception:
            logger.exception(
                "L0 attention update finalizer failed",
                extra={"turn_count": len(turns)},
            )

    def _retry_delay_seconds(self, failure_count: int) -> float:
        if self._retry_initial_seconds <= 0:
            return 0.0
        exponent = max(0, int(failure_count) - 1)
        return min(
            self._retry_max_seconds,
            self._retry_initial_seconds * (2**exponent),
        )

    def _current_policy(self) -> _AttentionUpdatePolicy:
        try:
            raw = self._config_getter()
            config = getattr(raw, "l0", raw)
        except Exception:
            config = None

        threshold = self._coerce_int(
            getattr(config, "attention_update_turn_threshold", None),
            DEFAULT_ATTENTION_UPDATE_TURN_THRESHOLD,
            minimum=1,
        )
        idle_seconds = self._coerce_float(
            getattr(config, "attention_update_idle_seconds", None),
            DEFAULT_ATTENTION_UPDATE_IDLE_SECONDS,
            minimum=0.0,
        )
        max_delay_seconds = self._coerce_float(
            getattr(config, "attention_update_max_delay_seconds", None),
            DEFAULT_ATTENTION_UPDATE_MAX_DELAY_SECONDS,
            minimum=0.0,
        )
        max_delay_seconds = max(idle_seconds, max_delay_seconds)
        return _AttentionUpdatePolicy(
            turn_threshold=threshold,
            idle_seconds=idle_seconds,
            max_delay_seconds=max_delay_seconds,
        )

    def _refresh_idle_event_locked(self) -> None:
        if self._has_pending_work_locked():
            self._idle_event.clear()
        else:
            self._idle_event.set()

    def _has_pending_work_locked(self) -> bool:
        return any(state.pending or state.processing for state in self._states.values())

    @staticmethod
    def _normalize_turn(
        turn: AcceptedL0AttentionTurn,
    ) -> AcceptedL0AttentionTurn | None:
        session_id = str(turn.session_id or "").strip()
        turn_id = str(turn.turn_id or "").strip()
        if not session_id or not turn_id:
            return None
        user_id = str(turn.user_id or "").strip()
        try:
            accepted_at = float(turn.accepted_at)
        except (TypeError, ValueError):
            accepted_at = time.time()
        if not math.isfinite(accepted_at) or accepted_at <= 0:
            accepted_at = time.time()
        if (
            session_id == turn.session_id
            and turn_id == turn.turn_id
            and user_id == turn.user_id
            and accepted_at == turn.accepted_at
        ):
            return turn
        return replace(
            turn,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            accepted_at=accepted_at,
        )

    @staticmethod
    def _coerce_int(value: Any, default: int, *, minimum: int) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value: Any, default: float, *, minimum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return max(minimum, parsed)


def should_update_attention_immediately(
    *,
    user_message: str,
    incoming_fact_kind: str | None,
) -> bool:
    """Identify explicit changes that should bypass normal batching delays."""

    fact_kind = str(incoming_fact_kind or "").strip().lower()
    if fact_kind in _IMMEDIATE_FACT_KINDS:
        return True
    message = " ".join(str(user_message or "").split())
    if not message:
        return False
    return any(pattern.search(message) is not None for pattern in _IMMEDIATE_MESSAGE_PATTERNS)


__all__ = [
    "AcceptedL0AttentionTurn",
    "AttentionBatch",
    "AttentionBatchFinalizer",
    "AttentionBatchProcessor",
    "L0AttentionUpdateScheduler",
    "should_update_attention_immediately",
]
