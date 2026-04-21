"""Runtime-singleton scheduler for background tasks.

The manager owns the in-memory concurrency primitives (semaphore, pending
queue, task table) and drives :class:`BackgroundTaskExecutor` instances.
It is the single external entry-point used by chat handlers, the REST
router, and the periodic recovery hook.

Lifecycle:

1. Call :meth:`start` once at bootstrap. It runs restart recovery
   (``running`` / ``cancelling`` rows from a previous process become
   ``failed(reason="backend_restart")``), rehydrates any leftover
   ``pending`` rows into the in-memory queue, and spawns the dispatcher
   loop.
2. During normal operation callers use :meth:`enqueue`, :meth:`cancel`,
   :meth:`retry`, :meth:`list_active`, :meth:`list_pending`.
3. On shutdown call :meth:`stop`: the dispatcher loop exits, all
   in-flight asyncio tasks are cancelled, and the manager waits for
   them to unwind gracefully.

The executor is pluggable so phase 3 can swap in the concrete
``FunctionCallingOrchestrator``-backed run function without changing
this module.
"""

from __future__ import annotations

import asyncio
from typing import Callable

import structlog

from ..cancel import EventCancelToken
from .contracts import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
)
from .executor import BackgroundTaskExecutor, BackgroundTaskRunFn
from .store import BackgroundTaskStore

__all__ = ["BackgroundTaskManager"]


logger = structlog.get_logger(__name__)


class BackgroundTaskManager:
    """Schedules :class:`BackgroundTask` runs under a concurrency cap."""

    def __init__(
        self,
        *,
        store: BackgroundTaskStore,
        run_fn: BackgroundTaskRunFn,
        max_concurrent: int = 2,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be >= 1")
        self._store = store
        self._run_fn = run_fn
        self._max_concurrent = max_concurrent
        self._clock = clock
        self._executor: BackgroundTaskExecutor | None = None
        self._queue: asyncio.Queue[BackgroundTask] | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._dispatcher_task: asyncio.Task[None] | None = None
        # task_id -> (cancel token, asyncio task running the attempt).
        self._running: dict[str, tuple[EventCancelToken, asyncio.Task[BackgroundTask]]] = {}
        self._started = False
        self._stopping = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Idempotent: safe to call multiple times. Second call is a noop."""
        if self._started:
            return
        await self._store.initialize()
        executor_kwargs: dict[str, object] = {
            "store": self._store,
            "run_fn": self._run_fn,
        }
        if self._clock is not None:
            executor_kwargs["clock"] = self._clock
        self._executor = BackgroundTaskExecutor(**executor_kwargs)  # type: ignore[arg-type]
        self._queue = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        recovered = await self._store.recover_stale_running()
        if recovered:
            logger.info(
                "background tasks recovered from restart",
                count=len(recovered),
                task_ids=[t.task_id for t in recovered],
            )
            for task in recovered:
                await self._store.append_event(
                    BackgroundTaskEvent.transition(
                        task_id=task.task_id,
                        attempt_index=task.attempt_index,
                        from_status=BackgroundTaskStatus.RUNNING,
                        to_status=BackgroundTaskStatus.FAILED,
                        message="backend_restart",
                    )
                )

        pending = await self._store.list_pending()
        for task in pending:
            self._queue.put_nowait(task)

        self._dispatcher_task = asyncio.create_task(
            self._dispatch_loop(), name="background-task-dispatcher"
        )
        self._started = True
        logger.info(
            "background task manager started",
            max_concurrent=self._max_concurrent,
            pending_rehydrated=len(pending),
            failed_on_restart=len(recovered),
        )

    async def stop(self) -> None:
        """Cancel the dispatcher and any in-flight attempts."""
        if not self._started or self._stopping:
            return
        self._stopping = True

        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._dispatcher_task = None

        # Snapshot to avoid mutating during iteration when tasks finish.
        in_flight = list(self._running.items())
        for task_id, (token, attempt_task) in in_flight:
            token.cancel(reason="shutdown")
            if not attempt_task.done():
                attempt_task.cancel()
        for task_id, (_, attempt_task) in in_flight:
            try:
                await attempt_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                logger.debug(
                    "background task attempt did not exit cleanly on stop",
                    bg_task_id=task_id,
                )

        self._running.clear()
        self._started = False
        self._stopping = False
        logger.info("background task manager stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, spec: BackgroundTaskSpec) -> BackgroundTask:
        """Persist a new pending task and queue it for execution."""
        self._require_started()
        task = BackgroundTask.new(spec)
        await self._store.create_task(task)
        await self._store.append_event(
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=None,
                to_status=BackgroundTaskStatus.PENDING,
                message=spec.trigger_source.value,
            )
        )
        assert self._queue is not None
        self._queue.put_nowait(task)
        logger.info(
            "background task enqueued",
            bg_task_id=task.task_id,
            trigger=spec.trigger_source.value,
            title=spec.title,
        )
        return task

    async def cancel(self, task_id: str, *, reason: str = "user_requested") -> bool:
        """Request cancellation of a running or pending task.

        Returns ``True`` when a cancellation was actually triggered,
        ``False`` if the task is unknown or already terminal.
        """
        self._require_started()
        async with self._lock:
            entry = self._running.get(task_id)
            if entry is not None:
                token, _ = entry
                token.cancel(reason=reason)
                task = await self._store.get_task(task_id)
                if task is not None and task.status == BackgroundTaskStatus.RUNNING:
                    previous = task.status
                    task.status = BackgroundTaskStatus.CANCELLING
                    task.cancel_reason = reason
                    await self._store.update_task(task)
                    await self._store.append_event(
                        BackgroundTaskEvent.transition(
                            task_id=task.task_id,
                            attempt_index=task.attempt_index,
                            from_status=previous,
                            to_status=BackgroundTaskStatus.CANCELLING,
                            message=reason,
                        )
                    )
                return True

            task = await self._store.get_task(task_id)
            if task is None:
                return False
            if task.status != BackgroundTaskStatus.PENDING:
                return False
            # Pending task has not been dispatched yet; flip straight to
            # cancelled. The dispatcher loop observes the new status when
            # it finally pulls the task off the queue and skips it.
            previous = task.status
            task.status = BackgroundTaskStatus.CANCELLED
            task.cancel_reason = reason
            task.finished_at = (
                self._clock() if self._clock is not None else task.created_at
            )
            task.updated_at = task.finished_at
            await self._store.update_task(task)
            await self._store.append_event(
                BackgroundTaskEvent.transition(
                    task_id=task.task_id,
                    attempt_index=task.attempt_index,
                    from_status=previous,
                    to_status=BackgroundTaskStatus.CANCELLED,
                    message=reason,
                )
            )
            return True

    async def retry(self, task_id: str) -> BackgroundTask | None:
        """Re-queue a terminal task as a new attempt.

        Only ``FAILED`` and ``CANCELLED`` rows may be retried; the
        attempt counter is bumped and the row is reset to ``PENDING``.
        Returns the updated task, or ``None`` if the task is unknown or
        not in a retriable state.
        """
        self._require_started()
        task = await self._store.get_task(task_id)
        if task is None:
            return None
        if task.status not in (
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.CANCELLED,
        ):
            return None
        previous = task.status
        task.status = BackgroundTaskStatus.PENDING
        task.attempt_index += 1
        task.error = None
        task.cancel_reason = None
        task.summary = None
        task.result_payload = {}
        task.started_at = None
        task.finished_at = None
        task.updated_at = (
            self._clock() if self._clock is not None else task.created_at
        )
        await self._store.update_task(task)
        await self._store.append_event(
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=previous,
                to_status=BackgroundTaskStatus.PENDING,
                message="retry",
            )
        )
        assert self._queue is not None
        self._queue.put_nowait(task)
        return task

    def list_active(self) -> list[str]:
        """Return task ids currently occupying a concurrency slot."""
        return list(self._running.keys())

    def active_count(self) -> int:
        return len(self._running)

    # ------------------------------------------------------------------
    # Dispatcher loop
    # ------------------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        assert self._queue is not None
        assert self._semaphore is not None
        assert self._executor is not None
        while True:
            task = await self._queue.get()
            if self._stopping:
                return
            # A pending task may have been cancelled before we reached
            # it; re-read the authoritative status from the store.
            latest = await self._store.get_task(task.task_id)
            if latest is None or latest.status != BackgroundTaskStatus.PENDING:
                continue
            task = latest
            await self._semaphore.acquire()
            if self._stopping:
                self._semaphore.release()
                return
            # Re-check after semaphore acquire: the task may have been
            # cancelled (or otherwise advanced) while we were blocked.
            latest = await self._store.get_task(task.task_id)
            if latest is None or latest.status != BackgroundTaskStatus.PENDING:
                self._semaphore.release()
                continue
            task = latest
            cancel_token = EventCancelToken()
            attempt_task = asyncio.create_task(
                self._run_attempt(task, cancel_token),
                name=f"background-task:{task.task_id}",
            )
            self._running[task.task_id] = (cancel_token, attempt_task)

    async def _run_attempt(
        self,
        task: BackgroundTask,
        cancel_token: EventCancelToken,
    ) -> BackgroundTask:
        assert self._executor is not None
        assert self._semaphore is not None
        try:
            return await self._executor.execute(task, cancel_token)
        finally:
            self._running.pop(task.task_id, None)
            self._semaphore.release()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError(
                "BackgroundTaskManager has not been started. Call start() first."
            )
