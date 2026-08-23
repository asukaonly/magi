"""Task-wide execution budgets shared by parent and worker agents."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator, Protocol

DEFAULT_TASK_MAX_LLM_CALLS = 30
DEFAULT_TASK_MAX_WORKER_LAUNCHES = 8


class TaskBudgetExceeded(RuntimeError):
    """Raised when one task attempts to exceed a shared execution limit."""

    def __init__(
        self,
        *,
        resource: str,
        limit: int,
        used: int,
        requested: int,
    ) -> None:
        self.resource = resource
        self.limit = limit
        self.used = used
        self.requested = requested
        super().__init__(
            f"Task budget exceeded for {resource}: "
            f"used={used}, requested={requested}, limit={limit}"
        )


class TaskExecutionBudgetStore(Protocol):
    """Persistence contract for one root turn's execution counters."""

    async def ensure_task_execution_budget(
        self,
        *,
        root_turn_id: str,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> tuple[int, int, int, int]: ...

    async def reserve_task_execution_budget(
        self,
        *,
        root_turn_id: str,
        resource: str,
        count: int,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> tuple[bool, int, int, int, int]: ...

    async def release_task_execution_llm_calls(
        self,
        *,
        root_turn_id: str,
        count: int,
    ) -> tuple[int, int, int, int] | None: ...


@dataclass(slots=True)
class TaskExecutionBudget:
    """Counters shared by every branch and admission of one root task."""

    max_llm_calls: int = DEFAULT_TASK_MAX_LLM_CALLS
    max_worker_launches: int = DEFAULT_TASK_MAX_WORKER_LAUNCHES
    llm_calls: int = 0
    worker_launches: int = 0
    root_turn_id: str | None = None
    store: TaskExecutionBudgetStore | None = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def initialize(self) -> None:
        """Create or reload the durable projection when persistence is bound."""
        if self.store is None or self.root_turn_id is None:
            return
        async with self._lock:
            state = await self.store.ensure_task_execution_budget(
                root_turn_id=self.root_turn_id,
                max_llm_calls=self.max_llm_calls,
                max_worker_launches=self.max_worker_launches,
            )
            self._apply_state(state)

    async def reserve_llm_calls(self, count: int = 1) -> None:
        await self._reserve(
            resource="llm_calls",
            count=count,
            used_attribute="llm_calls",
            limit=self.max_llm_calls,
        )

    async def reserve_worker_launches(self, count: int = 1) -> None:
        await self._reserve(
            resource="worker_launches",
            count=count,
            used_attribute="worker_launches",
            limit=self.max_worker_launches,
        )

    async def release_llm_calls(self, count: int = 1) -> None:
        """Release capacity reserved for calls that will no longer run."""
        if count < 1:
            raise ValueError("Task budget releases must be positive")
        async with self._lock:
            if self.store is not None and self.root_turn_id is not None:
                state = await self.store.release_task_execution_llm_calls(
                    root_turn_id=self.root_turn_id,
                    count=count,
                )
                if state is not None:
                    self._apply_state(state)
                return
            if count > self.llm_calls:
                raise ValueError("Cannot release more LLM calls than are reserved")
            self.llm_calls -= count

    async def _reserve(
        self,
        *,
        resource: str,
        count: int,
        used_attribute: str,
        limit: int,
    ) -> None:
        if count < 1:
            raise ValueError("Task budget reservations must be positive")
        async with self._lock:
            if self.store is not None and self.root_turn_id is not None:
                reservation = await self.store.reserve_task_execution_budget(
                    root_turn_id=self.root_turn_id,
                    resource=resource,
                    count=count,
                    max_llm_calls=self.max_llm_calls,
                    max_worker_launches=self.max_worker_launches,
                )
                accepted, max_llm, llm_used, max_workers, workers_used = reservation
                self._apply_state((max_llm, llm_used, max_workers, workers_used))
                if not accepted:
                    used = int(getattr(self, used_attribute))
                    raise TaskBudgetExceeded(
                        resource=resource,
                        limit=int(getattr(self, f"max_{resource}")),
                        used=used,
                        requested=count,
                    )
                return
            used = int(getattr(self, used_attribute))
            if used + count > limit:
                raise TaskBudgetExceeded(
                    resource=resource,
                    limit=limit,
                    used=used,
                    requested=count,
                )
            setattr(self, used_attribute, used + count)

    def _apply_state(self, state: tuple[int, int, int, int]) -> None:
        (
            self.max_llm_calls,
            self.llm_calls,
            self.max_worker_launches,
            self.worker_launches,
        ) = (int(value) for value in state)


_CURRENT_TASK_BUDGET: ContextVar[TaskExecutionBudget | None] = ContextVar(
    "magi_current_task_budget",
    default=None,
)


@dataclass(frozen=True, slots=True)
class _TaskLlmReservationFrame:
    """One scope's branch-local prepaid continuation capacity."""

    frame_id: object
    owner: object | None
    prepaid_calls: int = 0


_TASK_LLM_RESERVATION_FRAMES: ContextVar[tuple[_TaskLlmReservationFrame, ...]] = ContextVar(
    "magi_task_llm_reservation_frames",
    default=(),
)


def current_task_budget() -> TaskExecutionBudget | None:
    """Return the budget bound to the current async execution context."""
    return _CURRENT_TASK_BUDGET.get()


@asynccontextmanager
async def task_execution_budget_scope(
    *,
    max_llm_calls: int = DEFAULT_TASK_MAX_LLM_CALLS,
    max_worker_launches: int = DEFAULT_TASK_MAX_WORKER_LAUNCHES,
    root_turn_id: str | None = None,
    store: TaskExecutionBudgetStore | None = None,
) -> AsyncIterator[TaskExecutionBudget]:
    """Create or rehydrate a root budget and add an isolated reservation frame."""
    normalized_root_turn_id = str(root_turn_id or "").strip() or None
    if (normalized_root_turn_id is None) != (store is None):
        raise ValueError("Persistent task budgets require both root_turn_id and store")
    existing = current_task_budget()
    if (
        existing is not None
        and normalized_root_turn_id is not None
        and existing.root_turn_id != normalized_root_turn_id
    ):
        raise RuntimeError("Cannot bind two root turns to one execution context")
    budget = existing or TaskExecutionBudget(
        max_llm_calls=max_llm_calls,
        max_worker_launches=max_worker_launches,
        root_turn_id=normalized_root_turn_id,
        store=store,
    )
    if existing is None:
        await budget.initialize()
    budget_token = _CURRENT_TASK_BUDGET.set(budget) if existing is None else None
    inherited_frames = _TASK_LLM_RESERVATION_FRAMES.get() if existing is not None else ()
    frame = _TaskLlmReservationFrame(
        frame_id=object(),
        owner=asyncio.current_task(),
    )
    frames_token = _TASK_LLM_RESERVATION_FRAMES.set((*inherited_frames, frame))
    try:
        yield budget
    finally:
        try:
            await _release_prepaid_frame(frame.frame_id, budget=budget)
        finally:
            _TASK_LLM_RESERVATION_FRAMES.reset(frames_token)
            if budget_token is not None:
                _CURRENT_TASK_BUDGET.reset(budget_token)


@contextmanager
def fresh_task_execution_budget_context() -> Iterator[None]:
    """Clear request-local budget state while creating a persistent actor task."""
    budget_token = _CURRENT_TASK_BUDGET.set(None)
    frames_token = _TASK_LLM_RESERVATION_FRAMES.set(())
    try:
        yield
    finally:
        _TASK_LLM_RESERVATION_FRAMES.reset(frames_token)
        _CURRENT_TASK_BUDGET.reset(budget_token)


async def reserve_task_llm_calls(count: int = 1) -> None:
    """Reserve logical model calls when a task budget is active."""
    budget = current_task_budget()
    if budget is not None:
        await budget.reserve_llm_calls(count)


async def prepay_task_llm_calls(count: int = 1) -> None:
    """Ensure future main-model calls are reserved for the current branch."""
    if count < 1:
        raise ValueError("Task budget prepayments must be positive")
    budget = current_task_budget()
    if budget is None:
        return
    owner = asyncio.current_task()
    frames = _TASK_LLM_RESERVATION_FRAMES.get()
    frame_index = _find_owned_frame(frames, owner)
    if frame_index is None:
        frames = (
            *frames,
            _TaskLlmReservationFrame(frame_id=object(), owner=owner),
        )
        frame_index = len(frames) - 1
    frame = frames[frame_index]
    prepaid = frame.prepaid_calls
    additional = max(0, count - prepaid)
    if additional:
        await budget.reserve_llm_calls(additional)
    _TASK_LLM_RESERVATION_FRAMES.set(
        _replace_frame(
            frames,
            frame_index,
            _TaskLlmReservationFrame(
                frame_id=frame.frame_id,
                owner=frame.owner,
                prepaid_calls=max(prepaid, count),
            ),
        )
    )


async def consume_task_llm_calls(count: int = 1) -> None:
    """Charge calls, consuming branch-local prepaid capacity first."""
    if count < 1:
        raise ValueError("Task budget consumption must be positive")
    budget = current_task_budget()
    if budget is None:
        return
    owner = asyncio.current_task()
    frames = _TASK_LLM_RESERVATION_FRAMES.get()
    frame_index = _find_owned_frame(frames, owner)
    prepaid = frames[frame_index].prepaid_calls if frame_index is not None else 0
    prepaid_used = min(prepaid, count)
    unreserved = count - prepaid_used
    if unreserved:
        await budget.reserve_llm_calls(unreserved)
    if prepaid_used and frame_index is not None:
        frame = frames[frame_index]
        _TASK_LLM_RESERVATION_FRAMES.set(
            _replace_frame(
                frames,
                frame_index,
                _TaskLlmReservationFrame(
                    frame_id=frame.frame_id,
                    owner=frame.owner,
                    prepaid_calls=prepaid - prepaid_used,
                ),
            )
        )


async def release_prepaid_task_llm_calls() -> int:
    """Release the innermost unused reservation owned by this asyncio task."""
    budget = current_task_budget()
    if budget is None:
        return 0
    owner = asyncio.current_task()
    frames = _TASK_LLM_RESERVATION_FRAMES.get()
    frame_index = _find_owned_frame(frames, owner)
    if frame_index is None:
        return 0
    return await _release_prepaid_frame(frames[frame_index].frame_id, budget=budget)


def _find_owned_frame(
    frames: tuple[_TaskLlmReservationFrame, ...],
    owner: object | None,
) -> int | None:
    for index in range(len(frames) - 1, -1, -1):
        if frames[index].owner is owner:
            return index
    return None


def _replace_frame(
    frames: tuple[_TaskLlmReservationFrame, ...],
    index: int,
    replacement: _TaskLlmReservationFrame,
) -> tuple[_TaskLlmReservationFrame, ...]:
    return (*frames[:index], replacement, *frames[index + 1 :])


async def _release_prepaid_frame(
    frame_id: object,
    *,
    budget: TaskExecutionBudget,
) -> int:
    frames = _TASK_LLM_RESERVATION_FRAMES.get()
    for index in range(len(frames) - 1, -1, -1):
        frame = frames[index]
        if frame.frame_id is not frame_id:
            continue
        prepaid = frame.prepaid_calls
        if prepaid < 1:
            return 0
        # Claim the reservation before awaiting the durable refund. A commit may
        # succeed even when cancellation or connection teardown prevents the
        # store call from returning. Retrying that ambiguous refund would risk
        # subtracting calls consumed by another branch, so uncertainty is
        # handled conservatively as charged capacity.
        _TASK_LLM_RESERVATION_FRAMES.set(
            _replace_frame(
                frames,
                index,
                _TaskLlmReservationFrame(
                    frame_id=frame.frame_id,
                    owner=frame.owner,
                ),
            )
        )
        await budget.release_llm_calls(prepaid)
        return prepaid
    return 0


async def reserve_task_worker_launches(count: int = 1) -> None:
    """Reserve worker starts atomically when a task budget is active."""
    budget = current_task_budget()
    if budget is not None:
        await budget.reserve_worker_launches(count)


__all__ = [
    "DEFAULT_TASK_MAX_LLM_CALLS",
    "DEFAULT_TASK_MAX_WORKER_LAUNCHES",
    "TaskBudgetExceeded",
    "TaskExecutionBudget",
    "TaskExecutionBudgetStore",
    "consume_task_llm_calls",
    "current_task_budget",
    "fresh_task_execution_budget_context",
    "prepay_task_llm_calls",
    "release_prepaid_task_llm_calls",
    "reserve_task_llm_calls",
    "reserve_task_worker_launches",
    "task_execution_budget_scope",
]
