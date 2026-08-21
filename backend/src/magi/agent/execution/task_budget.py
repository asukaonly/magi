"""Task-wide execution budgets shared by parent and worker agents."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator

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


@dataclass(slots=True)
class TaskExecutionBudget:
    """Mutable counters shared by every in-process branch of one task."""

    max_llm_calls: int = DEFAULT_TASK_MAX_LLM_CALLS
    max_worker_launches: int = DEFAULT_TASK_MAX_WORKER_LAUNCHES
    llm_calls: int = 0
    worker_launches: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

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
            used = int(getattr(self, used_attribute))
            if used + count > limit:
                raise TaskBudgetExceeded(
                    resource=resource,
                    limit=limit,
                    used=used,
                    requested=count,
                )
            setattr(self, used_attribute, used + count)


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
) -> AsyncIterator[TaskExecutionBudget]:
    """Create a root budget or reuse it through an isolated reservation frame."""
    existing = current_task_budget()
    budget = existing or TaskExecutionBudget(
        max_llm_calls=max_llm_calls,
        max_worker_launches=max_worker_launches,
    )
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
        await budget.release_llm_calls(prepaid)
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
    "consume_task_llm_calls",
    "current_task_budget",
    "fresh_task_execution_budget_context",
    "prepay_task_llm_calls",
    "release_prepaid_task_llm_calls",
    "reserve_task_llm_calls",
    "reserve_task_worker_launches",
    "task_execution_budget_scope",
]
