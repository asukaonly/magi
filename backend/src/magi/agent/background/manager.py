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
import time
from collections.abc import AsyncIterator
from copy import deepcopy
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Awaitable, Callable

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

__all__ = [
    "BackgroundTaskAdmissionBlockedError",
    "BackgroundTaskAttemptListener",
    "BackgroundTaskListener",
    "BackgroundTaskManager",
    "TERMINAL_BACKGROUND_TASK_STATUSES",
]

#: Statuses that represent a run-to-completion outcome worth notifying
#: external observers about (completion handshake, UI refresh, etc.).
TERMINAL_BACKGROUND_TASK_STATUSES: frozenset[BackgroundTaskStatus] = frozenset(
    {
        BackgroundTaskStatus.SUCCEEDED,
        BackgroundTaskStatus.FAILED,
        BackgroundTaskStatus.CANCELLED,
    }
)

#: Callback invoked after a background task reaches a terminal status.
#: Implementations must be coroutine functions; raised exceptions are
#: caught and logged so one faulty listener cannot block the others.
BackgroundTaskListener = Callable[[BackgroundTask], Awaitable[None]]
BackgroundTaskAttemptListener = Callable[[BackgroundTask], Awaitable[None]]


logger = structlog.get_logger(__name__)


class BackgroundTaskAdmissionBlockedError(RuntimeError):
    """Raised when destructive conversation work rejects a new task."""


@dataclass(frozen=True, slots=True)
class _BackgroundTaskAdmissionScope:
    user_id: str | None
    session_id: str | None
    origin_turn_ids: frozenset[str] | None
    task_ids: frozenset[str] | None
    pending_message_ids: frozenset[str] | None

    @property
    def is_global(self) -> bool:
        return (
            self.user_id is None
            and self.session_id is None
            and self.origin_turn_ids is None
            and self.task_ids is None
            and self.pending_message_ids is None
        )

    def matches(self, *, task_id: str | None, spec: BackgroundTaskSpec) -> bool:
        if self.user_id is not None and spec.user_id != self.user_id:
            return False
        if self.session_id is not None and spec.session_id != self.session_id:
            return False
        identifiers = (
            self.origin_turn_ids,
            self.task_ids,
            self.pending_message_ids,
        )
        if all(values is None for values in identifiers):
            return True
        return bool(
            (
                self.origin_turn_ids is not None
                and spec.origin_turn_id in self.origin_turn_ids
            )
            or (
                self.task_ids is not None
                and task_id is not None
                and task_id in self.task_ids
            )
            or (
                self.pending_message_ids is not None
                and str(spec.pending_message_id or "").strip()
                in self.pending_message_ids
            )
        )


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
        self._terminal_notifications: dict[
            tuple[str, int],
            asyncio.Task[None],
        ] = {}
        self._attempt_notifications: dict[
            tuple[str, int],
            asyncio.Task[None],
        ] = {}
        self._listeners: list[BackgroundTaskListener] = []
        self._attempt_listeners: list[BackgroundTaskAttemptListener] = []
        self._started = False
        self._stopping = False
        self._lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._admission_scopes: dict[object, _BackgroundTaskAdmissionScope] = {}

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def store(self) -> BackgroundTaskStore:
        """Expose the underlying persistence store for read-only queries."""
        return self._store

    @property
    def max_concurrent(self) -> int:
        """Hard cap on simultaneously running background tasks (read-only)."""
        return self._max_concurrent

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
            "on_attempt_started": self._schedule_attempt_notification,
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
                await self._notify_listeners(task)

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

        notifications = list(self._terminal_notifications.values())
        if notifications:
            await asyncio.gather(*notifications, return_exceptions=True)
        self._terminal_notifications.clear()
        attempt_notifications = list(self._attempt_notifications.values())
        if attempt_notifications:
            await asyncio.gather(*attempt_notifications, return_exceptions=True)
        self._attempt_notifications.clear()
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
        async with self._admission_lock:
            self._assert_admitted(task_id=None, spec=spec)
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
        """Seal one scope against enqueue, then drain all existing work."""

        self._require_started()
        scope = self._normalized_admission_scope(
            user_id=user_id,
            session_id=session_id,
            origin_turn_ids=origin_turn_ids,
            task_ids=task_ids,
            pending_message_ids=pending_message_ids,
        )
        token = object()
        async with self._admission_lock:
            self._admission_scopes[token] = scope
        try:
            await self.cancel_scope_and_wait(
                user_id=user_id,
                session_id=session_id,
                origin_turn_ids=(
                    set(scope.origin_turn_ids)
                    if scope.origin_turn_ids is not None
                    else None
                ),
                task_ids=(
                    set(scope.task_ids)
                    if scope.task_ids is not None
                    else None
                ),
                pending_message_ids=(
                    set(scope.pending_message_ids)
                    if scope.pending_message_ids is not None
                    else None
                ),
                reason=reason,
                timeout_seconds=timeout_seconds,
            )
            yield
        finally:
            async with self._admission_lock:
                self._admission_scopes.pop(token, None)

    async def clear_all_history(self) -> dict[str, int]:
        """Delete every durable task record while global admission is sealed."""

        self._require_started()
        async with self._admission_lock:
            if not any(scope.is_global for scope in self._admission_scopes.values()):
                raise RuntimeError(
                    "Background task history clear requires a global admission seal"
                )
            return await self._store.clear_all()

    async def cancel(self, task_id: str, *, reason: str = "user_requested") -> bool:
        """Request cancellation of a running or pending task.

        Returns ``True`` when a cancellation was actually triggered,
        ``False`` if the task is unknown or already terminal.
        """
        self._require_started()
        terminal_task: BackgroundTask | None = None
        async with self._lock:
            entry = self._running.get(task_id)
            if entry is not None:
                token, _ = entry
                task = await self._store.persist_cancellation_request(
                    task_id=task_id,
                    reason=reason,
                    updated_at=(
                        self._clock()
                        if self._clock is not None
                        else time.time()
                    ),
                )
                if task is None:
                    return False
                token.cancel(reason=reason)
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
                self._clock() if self._clock is not None else time.time()
            )
            task.updated_at = task.finished_at
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
            terminal_task = task
        if terminal_task is not None:
            self._schedule_terminal_notification(terminal_task)
        return terminal_task is not None

    async def cancel_scope_and_wait(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        origin_turn_ids: set[str] | None = None,
        task_ids: set[str] | None = None,
        pending_message_ids: set[str] | None = None,
        reason: str = "conversation_deleted",
        timeout_seconds: float = 30.0,
    ) -> int:
        """Cancel matching work and wait through terminal listeners."""

        self._require_started()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, float(timeout_seconds))
        normalized_turn_ids = (
            {
                turn_id
                for raw_turn_id in origin_turn_ids
                if (turn_id := str(raw_turn_id or "").strip())
            }
            if origin_turn_ids is not None
            else None
        )
        normalized_task_ids = (
            {
                task_id
                for raw_task_id in task_ids
                if (task_id := str(raw_task_id or "").strip())
            }
            if task_ids is not None
            else None
        )
        normalized_pending_message_ids = (
            {
                message_id
                for raw_message_id in pending_message_ids
                if (message_id := str(raw_message_id or "").strip())
            }
            if pending_message_ids is not None
            else None
        )

        def matches(task: BackgroundTask) -> bool:
            if user_id is not None and task.spec.user_id != user_id:
                return False
            if session_id is not None and task.spec.session_id != session_id:
                return False
            identifiers = (
                normalized_turn_ids,
                normalized_task_ids,
                normalized_pending_message_ids,
            )
            if all(values is None for values in identifiers):
                return True
            return bool(
                (
                    normalized_turn_ids is not None
                    and task.spec.origin_turn_id in normalized_turn_ids
                )
                or (
                    normalized_task_ids is not None
                    and task.task_id in normalized_task_ids
                )
                or (
                    normalized_pending_message_ids is not None
                    and str(task.spec.pending_message_id or "").strip()
                    in normalized_pending_message_ids
                )
            )

        # Seal already-terminal pending completions before cancellation can
        # yield to a startup drain or another producer claim.
        await self._store.discard_pending_completions_in_scope(
            user_id=user_id,
            session_id=session_id,
            origin_turn_ids=normalized_turn_ids,
            task_ids=normalized_task_ids,
            pending_message_ids=normalized_pending_message_ids,
        )

        nonterminal = await self._store.list_tasks(
            user_id=user_id,
            session_id=session_id,
            statuses=[
                BackgroundTaskStatus.PENDING,
                BackgroundTaskStatus.RUNNING,
                BackgroundTaskStatus.CANCELLING,
                BackgroundTaskStatus.SUSPENDED_WAITING_USER,
            ],
            limit=10_000,
        )
        target_ids = {
            task.task_id
            for task in nonterminal
            if matches(task)
        }
        running_snapshot = list(self._running.items())
        for task_id, _entry in running_snapshot:
            task = await self._store.get_task(task_id)
            if task is not None and matches(task):
                target_ids.add(task_id)
        for task_id, _attempt_index in list(self._terminal_notifications):
            task = await self._store.get_task(task_id)
            if task is not None and matches(task):
                target_ids.add(task_id)
        for task_id, _attempt_index in list(self._attempt_notifications):
            task = await self._store.get_task(task_id)
            if task is not None and matches(task):
                target_ids.add(task_id)

        for task_id in sorted(target_ids):
            await self.cancel(task_id, reason=reason)

        attempts = [
            attempt
            for task_id, (_token, attempt) in list(self._running.items())
            if task_id in target_ids
        ]
        notifications = [
            notification
            for (task_id, _attempt_index), notification in list(
                self._terminal_notifications.items()
            )
            if task_id in target_ids
        ]
        attempt_notifications = [
            notification
            for (task_id, _attempt_index), notification in list(
                self._attempt_notifications.items()
            )
            if task_id in target_ids
        ]
        current = asyncio.current_task()
        if any(
            task is current
            for task in [
                *attempts,
                *notifications,
                *attempt_notifications,
            ]
        ):
            raise RuntimeError(
                "Background task cannot delete its own conversation scope"
            )
        waiters = [*attempts, *notifications, *attempt_notifications]
        if waiters:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(asyncio.shield(waiter) for waiter in waiters),
                    ),
                    timeout=max(0.001, deadline - loop.time()),
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    "Background conversation work did not stop before deletion"
                ) from exc

        while True:
            late_notifications = [
                notification
                for (task_id, _attempt_index), notification in [
                    *list(self._attempt_notifications.items()),
                    *list(self._terminal_notifications.items()),
                ]
                if task_id in target_ids and not notification.done()
            ]
            if not late_notifications:
                break
            if any(notification is current for notification in late_notifications):
                raise RuntimeError(
                    "Background task cannot delete its own conversation scope"
                )
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(
                            asyncio.shield(notification)
                            for notification in late_notifications
                        ),
                    ),
                    timeout=max(0.001, deadline - loop.time()),
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    "Background conversation work did not stop before deletion"
                ) from exc

        remaining = await self._store.list_tasks(
            user_id=user_id,
            session_id=session_id,
            statuses=[
                BackgroundTaskStatus.PENDING,
                BackgroundTaskStatus.RUNNING,
                BackgroundTaskStatus.CANCELLING,
                BackgroundTaskStatus.SUSPENDED_WAITING_USER,
            ],
            limit=10_000,
        )
        if any(matches(task) for task in remaining):
            raise RuntimeError(
                "Background conversation work remained active before deletion"
            )

        while True:
            _discarded, processing = (
                await self._store.discard_pending_completions_in_scope(
                    user_id=user_id,
                    session_id=session_id,
                    origin_turn_ids=normalized_turn_ids,
                    task_ids=normalized_task_ids,
                    pending_message_ids=normalized_pending_message_ids,
                )
            )
            if processing == 0:
                break
            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                raise RuntimeError(
                    "Background completion delivery did not stop before deletion"
                )
            await asyncio.sleep(min(0.01, remaining_seconds))
        return len(target_ids)

    async def suspend_waiting_user(
        self, task_id: str, *, reason: str = "awaiting_user_answer"
    ) -> bool:
        """Mark a running task as ``SUSPENDED_WAITING_USER``.

        Used by tools like ``ask_user_question`` while awaiting a
        frontend response. Returns ``True`` when the transition
        happened, ``False`` when the task is unknown or not currently
        ``RUNNING``.

        This method only updates durable state + the event log; it does
        not pause execution of the underlying coroutine. Callers are
        expected to continue awaiting their broker/response signal and
        then call :meth:`resume_from_wait` once the user has replied.
        """
        self._require_started()
        task = await self._store.get_task(task_id)
        if task is None:
            return False
        if task.status != BackgroundTaskStatus.RUNNING:
            return False
        previous = task.status
        task.status = BackgroundTaskStatus.SUSPENDED_WAITING_USER
        now = self._clock() if self._clock is not None else task.created_at
        task.updated_at = now
        await self._store.update_task(task)
        await self._store.append_event(
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=previous,
                to_status=BackgroundTaskStatus.SUSPENDED_WAITING_USER,
                message=reason,
            )
        )
        return True

    async def resume_from_wait(self, task_id: str) -> bool:
        """Transition a suspended task back to ``RUNNING``.

        Symmetric to :meth:`suspend_waiting_user`. Returns ``True`` on
        a successful transition, ``False`` when the task is unknown or
        not in ``SUSPENDED_WAITING_USER``.
        """
        self._require_started()
        task = await self._store.get_task(task_id)
        if task is None:
            return False
        if task.status != BackgroundTaskStatus.SUSPENDED_WAITING_USER:
            return False
        previous = task.status
        task.status = BackgroundTaskStatus.RUNNING
        now = self._clock() if self._clock is not None else task.created_at
        task.updated_at = now
        await self._store.update_task(task)
        await self._store.append_event(
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=previous,
                to_status=BackgroundTaskStatus.RUNNING,
                message="resumed_from_wait",
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
        async with self._admission_lock:
            task = await self._store.get_task(task_id)
            if task is None:
                return None
            if task.status not in (
                BackgroundTaskStatus.FAILED,
                BackgroundTaskStatus.CANCELLED,
            ):
                return None
            self._assert_admitted(task_id=task.task_id, spec=task.spec)
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

    def _assert_admitted(
        self,
        *,
        task_id: str | None,
        spec: BackgroundTaskSpec,
    ) -> None:
        if any(
            scope.matches(task_id=task_id, spec=spec)
            for scope in self._admission_scopes.values()
        ):
            raise BackgroundTaskAdmissionBlockedError(
                "Background task belongs to a conversation being deleted"
            )

    @staticmethod
    def _normalized_admission_scope(
        *,
        user_id: str | None,
        session_id: str | None,
        origin_turn_ids: set[str] | None,
        task_ids: set[str] | None,
        pending_message_ids: set[str] | None,
    ) -> _BackgroundTaskAdmissionScope:
        def normalized(values: set[str] | None) -> frozenset[str] | None:
            if values is None:
                return None
            return frozenset(
                value
                for raw_value in values
                if (value := str(raw_value or "").strip())
            )

        return _BackgroundTaskAdmissionScope(
            user_id=str(user_id or "").strip() or None,
            session_id=str(session_id or "").strip() or None,
            origin_turn_ids=normalized(origin_turn_ids),
            task_ids=normalized(task_ids),
            pending_message_ids=normalized(pending_message_ids),
        )

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
            if latest.task_id in self._running:
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
            if latest.task_id in self._running:
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
            finished = await self._executor.execute(task, cancel_token)
            if finished.status in TERMINAL_BACKGROUND_TASK_STATUSES:
                await self._notify_listeners(finished)
            return finished
        finally:
            self._running.pop(task.task_id, None)
            self._semaphore.release()
            # A retry may be admitted after the old attempt becomes durable
            # terminal but before its slow terminal listeners return. The
            # dispatcher consumes and skips that retry while this task is
            # still registered in ``_running``. Re-read durable state after
            # unregistering so the pending attempt cannot lose its wake-up.
            if not self._stopping and self._queue is not None:
                try:
                    latest = await self._store.get_task(task.task_id)
                except Exception:  # noqa: BLE001 - preserve attempt outcome
                    logger.exception(
                        "failed to recover pending retry after attempt exit",
                        bg_task_id=task.task_id,
                    )
                else:
                    if latest is not None and latest.status == BackgroundTaskStatus.PENDING:
                        self._queue.put_nowait(latest)

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def _schedule_terminal_notification(self, task: BackgroundTask) -> None:
        key = (task.task_id, int(task.attempt_index))
        existing = self._terminal_notifications.get(key)
        if existing is not None and not existing.done():
            return
        notification = asyncio.create_task(
            self._notify_listeners(task),
            name=f"background-task-notification:{task.task_id}:{task.attempt_index}",
        )
        self._terminal_notifications[key] = notification

        def discard(done: asyncio.Task[None]) -> None:
            if self._terminal_notifications.get(key) is done:
                self._terminal_notifications.pop(key, None)

        notification.add_done_callback(discard)

    async def _schedule_attempt_notification(self, task: BackgroundTask) -> None:
        """Schedule attempt-derived projections without blocking task execution."""

        snapshot = deepcopy(task)
        key = (snapshot.task_id, int(snapshot.attempt_index))
        existing = self._attempt_notifications.get(key)
        if existing is not None and not existing.done():
            return
        notification = asyncio.create_task(
            self._notify_attempt_listeners(snapshot),
            name=(
                "background-attempt-notification:"
                f"{snapshot.task_id}:{snapshot.attempt_index}"
            ),
        )
        self._attempt_notifications[key] = notification

        def discard(done: asyncio.Task[None]) -> None:
            if self._attempt_notifications.get(key) is done:
                self._attempt_notifications.pop(key, None)

        notification.add_done_callback(discard)

    def add_listener(self, listener: BackgroundTaskListener) -> None:
        """Register a terminal-state listener.

        Listeners fire after each attempt reaches ``SUCCEEDED``,
        ``FAILED`` or ``CANCELLED``. They are invoked in registration
        order; one listener raising does not block the others.
        """
        if listener in self._listeners:
            return
        self._listeners.append(listener)

    def remove_listener(self, listener: BackgroundTaskListener) -> None:
        """Deregister a previously-added listener. No-op if unknown."""
        try:
            self._listeners.remove(listener)
        except ValueError:
            return

    def add_attempt_listener(
        self,
        listener: BackgroundTaskAttemptListener,
    ) -> None:
        """Register a listener for each durably started task attempt."""

        if listener not in self._attempt_listeners:
            self._attempt_listeners.append(listener)

    def remove_attempt_listener(
        self,
        listener: BackgroundTaskAttemptListener,
    ) -> None:
        """Deregister one attempt-start listener."""

        try:
            self._attempt_listeners.remove(listener)
        except ValueError:
            return

    async def _notify_attempt_listeners(self, task: BackgroundTask) -> None:
        for listener in list(self._attempt_listeners):
            try:
                await listener(task)
            except Exception:  # noqa: BLE001 - listener isolation
                logger.exception(
                    "background task attempt listener raised",
                    bg_task_id=task.task_id,
                    bg_attempt=task.attempt_index,
                )

    async def _notify_listeners(self, task: BackgroundTask) -> None:
        for listener in list(self._listeners):
            try:
                await listener(task)
            except Exception:  # noqa: BLE001 - listener isolation
                logger.exception(
                    "background task listener raised",
                    bg_task_id=task.task_id,
                    status=task.status.value,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError(
                "BackgroundTaskManager has not been started. Call start() first."
            )
