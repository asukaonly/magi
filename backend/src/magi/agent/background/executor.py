"""Runs a single BackgroundTask attempt to completion.

The executor is deliberately thin: it owns the state-machine transitions
(``pending → running → succeeded | failed | cancelled``) and the event
log, but delegates the actual work to a pluggable ``run_fn``. This lets
phase 2 ship the lifecycle scaffolding in isolation — phase 3 plugs in
``FunctionCallingOrchestrator.run`` as the concrete run
function.

Contract: ``run_fn(task, cancel_token)`` must

* poll ``cancel_token`` cooperatively (the standard pattern is to pass
  it to :meth:`FunctionCallingOrchestrator.run`),
* return a :class:`BackgroundTaskRunResult` on success,
* raise :class:`asyncio.CancelledError` if it observed a cancel request,
* raise any other exception to signal failure.

The executor translates these into durable state + event rows.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from ..cancel import CancelToken, EventCancelToken
from .contracts import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskStatus,
)
from .store import BackgroundTaskStore

__all__ = [
    "BackgroundTaskExecutor",
    "BackgroundTaskRunFn",
    "BackgroundTaskRunResult",
]


logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class BackgroundTaskRunResult:
    """Structured successful outcome returned by a ``run_fn``."""

    summary: str | None = None
    result_payload: dict[str, Any] = field(default_factory=dict)


BackgroundTaskRunFn = Callable[
    [BackgroundTask, CancelToken], Awaitable[BackgroundTaskRunResult]
]
BackgroundTaskAttemptStartedFn = Callable[[BackgroundTask], Awaitable[None]]


class BackgroundTaskExecutor:
    """Executes one :class:`BackgroundTask` attempt and persists its lifecycle."""

    def __init__(
        self,
        *,
        store: BackgroundTaskStore,
        run_fn: BackgroundTaskRunFn,
        clock: Callable[[], float] = time.time,
        on_attempt_started: BackgroundTaskAttemptStartedFn | None = None,
    ) -> None:
        self._store = store
        self._run_fn = run_fn
        self._clock = clock
        self._on_attempt_started = on_attempt_started

    async def execute(
        self,
        task: BackgroundTask,
        cancel_token: EventCancelToken,
    ) -> BackgroundTask:
        """Run ``task`` to a terminal state. Mutates ``task`` in place.

        ``cancel_token`` is an :class:`EventCancelToken` because the
        executor needs to distinguish "the caller requested cancellation
        before we even reached a terminal state" from arbitrary other
        exceptions. Pass a fresh token per attempt.
        """
        if not await self._transition_to_running(task):
            latest = await self._store.get_task(task.task_id)
            if latest is None:
                raise RuntimeError(
                    "Background task disappeared before attempt start"
                )
            if latest.status in BackgroundTaskStatus.terminal():
                return latest
            raise RuntimeError(
                "Background task attempt could not start from its durable state"
            )
        if self._on_attempt_started is not None:
            await self._on_attempt_started(task)
        try:
            result = await self._run_fn(task, cancel_token)
        except asyncio.CancelledError:
            await self._transition_to_cancelled(
                task, reason=cancel_token.reason or "cancelled"
            )
            # Swallow: the cancellation is a terminal state of this
            # attempt; the enclosing asyncio task finishes normally so
            # the manager can collect its result.
            return task
        except (
            asyncio.TimeoutError
        ):  # run_fn may wrap with wait_for and re-raise as-is
            await self._transition_to_failed(task, reason="timeout")
            return task
        except Exception as exc:  # noqa: BLE001 - terminal catch
            reason = self._classify_error(exc)
            logger.exception(
                "background task failed",
                bg_task_id=task.task_id,
                bg_attempt=task.attempt_index,
                reason=reason,
            )
            await self._transition_to_failed(task, reason=reason)
            return task

        if await cancel_token.is_cancelled():
            # The run_fn completed normally but a cancel was observed
            # concurrently (e.g. checked between the last probe and
            # return). Treat the attempt as cancelled so the UI reflects
            # user intent.
            await self._transition_to_cancelled(
                task, reason=cancel_token.reason or "cancelled"
            )
            return task

        await self._transition_to_succeeded(task, result)
        return task

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    async def _transition_to_running(self, task: BackgroundTask) -> bool:
        previous = task.status
        now = self._clock()
        task.status = BackgroundTaskStatus.RUNNING
        task.started_at = now
        task.updated_at = now
        task.error = None
        task.cancel_reason = None
        return await self._store.persist_running_transition(
            task,
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=previous,
                to_status=BackgroundTaskStatus.RUNNING,
            ),
        )

    async def _transition_to_succeeded(
        self,
        task: BackgroundTask,
        result: BackgroundTaskRunResult,
    ) -> None:
        previous = task.status
        now = self._clock()
        task.status = BackgroundTaskStatus.SUCCEEDED
        task.summary = result.summary
        task.result_payload = dict(result.result_payload or {})
        task.finished_at = now
        task.updated_at = now
        await self._store.persist_terminal_transition(
            task,
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=previous,
                to_status=BackgroundTaskStatus.SUCCEEDED,
            ),
        )

    async def _transition_to_failed(
        self, task: BackgroundTask, *, reason: str
    ) -> None:
        previous = task.status
        now = self._clock()
        task.status = BackgroundTaskStatus.FAILED
        task.error = reason
        task.finished_at = now
        task.updated_at = now
        await self._store.persist_terminal_transition(
            task,
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=previous,
                to_status=BackgroundTaskStatus.FAILED,
                message=reason,
            ),
        )

    async def _transition_to_cancelled(
        self, task: BackgroundTask, *, reason: str
    ) -> None:
        previous = task.status
        now = self._clock()
        task.status = BackgroundTaskStatus.CANCELLED
        task.cancel_reason = reason
        task.finished_at = now
        task.updated_at = now
        await self._store.persist_terminal_transition(
            task,
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=previous,
                to_status=BackgroundTaskStatus.CANCELLED,
                message=reason,
            ),
        )

    @staticmethod
    def _classify_error(exc: BaseException) -> str:
        message = str(exc).strip()
        qualified = f"{type(exc).__name__}"
        if message:
            return f"{qualified}: {message}"
        return qualified
