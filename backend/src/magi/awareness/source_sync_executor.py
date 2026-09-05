"""Dedicated queued executor for pull-based source sync jobs."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from ..core.logger import get_logger
from ..scheduler.contracts import (
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ..scheduler.repository import ScheduleRepository

logger = get_logger(__name__)

SourceSyncJobRunner = Callable[[dict[str, object]], Awaitable[ScheduledExecutionResult]]
SourceStateFlushRunner = Callable[..., Awaitable[dict[str, Any]]]
_ResultT = TypeVar("_ResultT")

_POST_SYNC_L3_BACKFILL_MAX_PERIODS = 4


class SourceSyncExecutorState(str, Enum):
    """Lifecycle state for the dedicated source sync worker."""

    STOPPED = "stopped"
    RUNNING = "running"
    STOPPING = "stopping"


class SourceSyncScheduler(Protocol):
    """Scheduler operations used after a source job commits."""

    async def execute_schedule_async(
        self,
        schedule_id: str,
        *,
        manual: bool = True,
        override_payload: dict[str, Any] | None = None,
    ) -> ScheduledExecutionResult: ...


class SourceSyncExecutor:
    """Run queued source sync jobs on a dedicated thread-local event loop."""

    def __init__(
        self,
        *,
        repository: ScheduleRepository,
        run_job: SourceSyncJobRunner,
        flush_state: SourceStateFlushRunner | None = None,
        scheduler_service: SourceSyncScheduler | None = None,
        poll_interval_seconds: float = 0.1,
        max_attempts: int = 4,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 300.0,
        stop_timeout_seconds: float = 5.0,
        worker_id: str = "source-sync-executor",
    ) -> None:
        self._repository = repository
        self._run_job = run_job
        self._flush_state = flush_state
        self._scheduler_service = scheduler_service
        self._poll_interval_seconds = poll_interval_seconds
        self._max_attempts = max(1, int(max_attempts))
        self._retry_base_seconds = max(0.0, float(retry_base_seconds))
        self._retry_max_seconds = max(
            self._retry_base_seconds,
            float(retry_max_seconds),
        )
        self._stop_timeout_seconds = max(0.0, float(stop_timeout_seconds))
        self._worker_id = worker_id
        self._lifecycle_lock = threading.Lock()
        self._state = SourceSyncExecutorState.STOPPED
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._stop_requested: threading.Event | None = None
        self._resume_requested: threading.Event | None = None
        self._execution_lock: asyncio.Lock | None = None
        self._post_sync_lock = threading.Lock()
        self._post_sync_sources: set[str] = set()
        self._post_sync_future: concurrent.futures.Future[None] | None = None
        self._ready = threading.Event()

    @property
    def state(self) -> SourceSyncExecutorState:
        """Return the current lifecycle state."""
        with self._lifecycle_lock:
            self._reap_exited_thread_locked()
            return self._state

    async def start(self, *, paused: bool = False) -> None:
        """Start the worker, optionally keeping it unable to claim jobs."""

        owner_loop = asyncio.get_running_loop()
        with self._lifecycle_lock:
            self._reap_exited_thread_locked()
            if self._state is SourceSyncExecutorState.STOPPING:
                raise RuntimeError(
                    "Source sync executor is still stopping; wait for the existing worker to exit"
                )
            if self._state is SourceSyncExecutorState.RUNNING:
                thread = self._thread
                if thread is not None and thread.is_alive():
                    return
                raise RuntimeError("Source sync executor worker state is inconsistent")

            existing_thread = self._thread
            if existing_thread is not None and existing_thread.is_alive():
                raise RuntimeError("Previous source sync executor worker has not exited")

            stop_requested = threading.Event()
            resume_requested = threading.Event()
            if not paused:
                resume_requested.set()
            self._owner_loop = owner_loop
            self._stop_requested = stop_requested
            self._resume_requested = resume_requested
            self._ready.clear()
            thread = threading.Thread(
                target=self._run_thread,
                args=(stop_requested, resume_requested),
                name=self._worker_id,
                daemon=True,
            )
            self._thread = thread
            self._state = SourceSyncExecutorState.RUNNING

            try:
                thread.start()
            except Exception:
                if self._thread is thread:
                    self._thread = None
                    self._owner_loop = None
                    self._stop_requested = None
                    self._resume_requested = None
                    self._state = SourceSyncExecutorState.STOPPED
                raise

        ready = await asyncio.to_thread(self._ready.wait, 5.0)
        if not ready:
            await self._handle_start_timeout(thread, stop_requested)

    def resume(self) -> None:
        """Release a successfully started paused worker to claim jobs."""

        with self._lifecycle_lock:
            self._reap_exited_thread_locked()
            resume_requested = self._resume_requested
            if self._state is not SourceSyncExecutorState.RUNNING or resume_requested is None:
                raise RuntimeError("Source sync executor is not ready to resume")
            resume_requested.set()

    async def stop(self) -> None:
        with self._lifecycle_lock:
            self._reap_exited_thread_locked()
            if self._state is SourceSyncExecutorState.STOPPED:
                return
            thread = self._thread
            if thread is None:
                raise RuntimeError("Source sync executor worker state is inconsistent")
            self._state = SourceSyncExecutorState.STOPPING
            stop_requested = self._stop_requested
            loop = self._loop
            stop_event = self._stop_event

        if stop_requested is not None:
            stop_requested.set()
        self._signal_stop(loop, stop_event)
        await asyncio.to_thread(thread.join, self._stop_timeout_seconds)
        if thread.is_alive():
            raise TimeoutError(
                "Timed out stopping source sync executor; the existing worker is still running"
            )

        with self._lifecycle_lock:
            self._reap_exited_thread_locked()

    async def _handle_start_timeout(
        self,
        thread: threading.Thread,
        stop_requested: threading.Event,
    ) -> None:
        stop_requested.set()
        with self._lifecycle_lock:
            if self._thread is thread:
                self._state = SourceSyncExecutorState.STOPPING
                loop = self._loop
                stop_event = self._stop_event
            else:
                loop = None
                stop_event = None
        self._signal_stop(loop, stop_event)
        await asyncio.to_thread(thread.join, self._stop_timeout_seconds)
        if thread.is_alive():
            raise TimeoutError(
                "Timed out starting source sync executor; the worker is still stopping"
            )
        with self._lifecycle_lock:
            self._reap_exited_thread_locked()
        raise RuntimeError("Timed out starting source sync executor thread")

    @staticmethod
    def _signal_stop(
        loop: asyncio.AbstractEventLoop | None,
        stop_event: asyncio.Event | None,
    ) -> None:
        if loop is None or stop_event is None:
            return
        try:
            loop.call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            return

    def _reap_exited_thread_locked(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        if thread is None and self._state is SourceSyncExecutorState.STOPPED:
            return
        self._thread = None
        self._loop = None
        self._owner_loop = None
        self._stop_event = None
        self._stop_requested = None
        self._resume_requested = None
        self._execution_lock = None
        self._state = SourceSyncExecutorState.STOPPED

    def _run_thread(
        self,
        stop_requested: threading.Event,
        resume_requested: threading.Event,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        execution_lock = asyncio.Lock()
        with self._lifecycle_lock:
            if self._thread is not threading.current_thread():
                loop.close()
                return
            self._loop = loop
            self._stop_event = stop_event
            self._execution_lock = execution_lock
        if stop_requested.is_set():
            stop_event.set()
        self._ready.set()
        try:
            loop.run_until_complete(self._run_loop(resume_requested))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                post_sync_future = self._clear_post_sync_queue()
                if post_sync_future is not None and not post_sync_future.done():
                    post_sync_future.cancel()
                with self._lifecycle_lock:
                    if self._thread is threading.current_thread():
                        self._loop = None
                        self._owner_loop = None
                        self._stop_event = None
                        self._resume_requested = None
                        self._execution_lock = None

    async def _run_loop(self, resume_requested: threading.Event) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            raise RuntimeError("Source sync executor stop event was not initialized")
        while not resume_requested.is_set():
            if stop_event.is_set():
                return
            await self._wait_for_next_poll(stop_event)

        await self._repository.recover_running_source_sync_jobs()

        while not stop_event.is_set():
            try:
                job = await self._repository.claim_next_source_sync_job(claimed_by=self._worker_id)
                if job is None:
                    await self._wait_for_next_poll(stop_event)
                    continue
                await self._execute_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Source sync executor loop failed", error=str(exc))
                try:
                    await self._repository.recover_running_source_sync_jobs()
                except Exception:
                    logger.exception("Source sync executor could not recover running jobs")
                await self._wait_for_next_poll(stop_event)

    async def _wait_for_next_poll(self, stop_event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_seconds)
        except asyncio.TimeoutError:
            return

    async def _execute_job(self, job: dict[str, object]) -> None:
        finished_at = time.time()
        target_type = ScheduledTargetType(str(job["target_type"]))
        target_key = str(job["target_key"])
        scheduler_binding = await self._repository.get_recurring_target_binding(target_type, target_key)
        scheduler_job_id = str(scheduler_binding[0]) if scheduler_binding is not None else None

        try:
            result = await self._run_with_execution_lock(self._run_on_owner_loop(self._run_job(job)))
            if not result.success:
                raise RuntimeError(result.message or "source_sync_failed")
        except Exception as exc:
            await self._settle_failed_job(
                job,
                scheduler_job_id=scheduler_job_id,
                error=exc,
            )
            return

        finished_at = time.time()
        continue_sync = self._result_requests_continuation(
            result
        ) and not self._job_disables_continuation(job)
        try:
            await self._repository.settle_source_sync_job_success(
                str(job["job_id"]),
                result=result,
                finished_at=finished_at,
                scheduler_job_id=scheduler_job_id,
                continue_sync=continue_sync,
            )
        except Exception as exc:
            persisted = await self._repository.get_source_sync_job(str(job["job_id"]))
            if persisted is None or persisted.get("status") != "success":
                await self._settle_failed_job(
                    job,
                    scheduler_job_id=scheduler_job_id,
                    error=exc,
                )
                return
            logger.warning(
                "Source sync success commit returned an error after persistence",
                job_id=str(job["job_id"]),
                error=str(exc),
            )

        if not continue_sync:
            self._queue_post_sync_maintenance(str(job["source_type"]))

    async def _settle_failed_job(
        self,
        job: dict[str, object],
        *,
        scheduler_job_id: str | None,
        error: Exception,
    ) -> None:
        finished_at = time.time()
        raw_attempt_count = job.get("attempt_count")
        attempt_count = max(
            1,
            raw_attempt_count if isinstance(raw_attempt_count, int) else 1,
        )
        retry_delay_seconds = min(
            self._retry_max_seconds,
            self._retry_base_seconds * (2 ** min(attempt_count - 1, 16)),
        )
        requeued = await self._repository.settle_source_sync_job_failure(
            str(job["job_id"]),
            error=str(error),
            failed_at=finished_at,
            retry_delay_seconds=retry_delay_seconds,
            max_attempts=self._max_attempts,
            scheduler_job_id=scheduler_job_id,
        )
        if requeued:
            logger.warning(
                "Source sync scheduled for retry",
                job_id=str(job["job_id"]),
                target_key=str(job["target_key"]),
                attempt_count=attempt_count,
                next_attempt_at=finished_at + retry_delay_seconds,
                error=str(error),
            )

    @staticmethod
    def _result_requests_continuation(result: ScheduledExecutionResult) -> bool:
        stats = result.stats or {}
        for key in ("has_more", "continue_sync", "backfill_has_more"):
            value = stats.get(key)
            if isinstance(value, str):
                if value.strip().lower() in {"1", "true", "yes", "y", "on"}:
                    return True
                continue
            if bool(value):
                return True
        return False

    @staticmethod
    def _job_disables_continuation(job: dict[str, object]) -> bool:
        payload = job.get("payload")
        if isinstance(payload, dict) and bool(payload.get("first_context")):
            return True
        return bool(job.get("first_context"))

    def _queue_post_sync_maintenance(self, source_name: str) -> None:
        source_name = source_name.strip()
        if not source_name:
            return
        owner_loop = self._owner_loop
        if owner_loop is None or owner_loop.is_closed():
            logger.warning(
                "post-sync maintenance skipped: owner loop unavailable",
                source=source_name,
            )
            return

        future: concurrent.futures.Future[None] | None = None
        with self._post_sync_lock:
            self._post_sync_sources.add(source_name)
            existing = self._post_sync_future
            if existing is not None and not existing.done():
                return
            coro = self._drain_post_sync_maintenance()
            try:
                future = asyncio.run_coroutine_threadsafe(coro, owner_loop)
            except RuntimeError:
                coro.close()
                self._post_sync_future = None
                logger.exception(
                    "post-sync maintenance scheduling failed",
                    source=source_name,
                )
                return
            self._post_sync_future = future
        future.add_done_callback(self._handle_post_sync_maintenance_done)

    async def _drain_post_sync_maintenance(self) -> None:
        while True:
            with self._post_sync_lock:
                if not self._post_sync_sources:
                    self._post_sync_future = None
                    return
                source_name = sorted(self._post_sync_sources)[0]
                self._post_sync_sources.remove(source_name)

            try:
                # Best-effort: fill L3 "Stories" for any CLOSED past periods this
                # source's data lands in. Historical imports land in already-closed
                # day/week windows the recurring scheduler never revisits. This runs
                # outside the serial source executor so slow LLM calls cannot stop
                # later source sync jobs from being claimed.
                await self._backfill_l3_after_sync(source_name)
                # Best-effort: kick the L2 derive task so newly-synced interests/
                # conflicts refresh promptly instead of waiting for the 6 h interval.
                await self._trigger_l2_derive_after_sync_current_loop()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "post-sync maintenance failed (non-fatal)",
                    source=source_name,
                )

    def _clear_post_sync_queue(self) -> concurrent.futures.Future[None] | None:
        with self._post_sync_lock:
            self._post_sync_sources.clear()
            future = self._post_sync_future
            self._post_sync_future = None
            return future

    def _handle_post_sync_maintenance_done(
        self,
        future: concurrent.futures.Future[None],
    ) -> None:
        try:
            future.result()
        except concurrent.futures.CancelledError:
            logger.debug("post-sync maintenance cancelled")
        except Exception as exc:
            logger.exception(
                "post-sync maintenance runner failed",
                error=str(exc),
            )

    async def _backfill_l3_after_sync(self, source_name: str) -> None:
        """Best-effort L3 historical backfill over a synced source's L1 window.

        Fully guarded: any failure here is logged and swallowed so it can never
        break a sync that already committed successfully.
        """
        try:
            from ..memory.provider import get_unified_memory

            unified_memory = get_unified_memory()
            rows = await unified_memory.l1.summarize_event_sources(
                source_filters=[source_name],
                cognition_eligible=True,
            )
            spans = [
                row
                for row in rows
                if row.get("min_timestamp") is not None
                and row.get("max_timestamp") is not None
            ]
            if not spans:
                return
            range_start = min(float(row["min_timestamp"]) for row in spans)
            range_end = max(float(row["max_timestamp"]) for row in spans)
            backfilled = await unified_memory.backfill_l3_gaps(
                range_start=range_start,
                range_end=range_end,
                max_periods=_POST_SYNC_L3_BACKFILL_MAX_PERIODS,
            )
            logger.info(
                "L3 backfill after source sync",
                source=source_name,
                generated=len(backfilled.get("generated", [])),
                skipped_existing=backfilled.get("skipped_existing", 0),
                skipped_sparse=backfilled.get("skipped_sparse", 0),
            )
        except Exception:  # pragma: no cover - defensive: L3 must never fail a sync
            logger.exception(
                "L3 backfill after source sync failed (non-fatal)",
                source=source_name,
            )

    async def _trigger_l2_derive_after_sync(self) -> None:
        """Best-effort: kick the L2 derive task so a just-synced source's interests/
        conflicts refresh promptly. Fully guarded — never breaks a committed sync.
        Non-blocking: uses execute_schedule_async so the sync return isn't delayed.
        Runs on the owner loop (where the scheduler service lives) via
        _run_on_owner_loop.
        """
        if self._running_on_owner_loop():
            await self._trigger_l2_derive_after_sync_current_loop()
            return
        await self._run_on_owner_loop(self._trigger_l2_derive_after_sync_current_loop())

    async def _trigger_l2_derive_after_sync_current_loop(self) -> None:
        if self._scheduler_service is None:
            return
        try:
            from ..memory.l2.derive_schedule import SCHEDULE_ID_L2_DERIVE

            await self._scheduler_service.execute_schedule_async(
                SCHEDULE_ID_L2_DERIVE,
                manual=True,
            )
        except Exception:
            logger.exception("post-sync L2 derive trigger failed (non-fatal)")

    def _running_on_owner_loop(self) -> bool:
        try:
            return asyncio.get_running_loop() is self._owner_loop
        except RuntimeError:
            return False

    async def flush_source_state(self, source_name: str, *, connection_id: str) -> dict[str, Any]:
        if self._flush_state is None:
            raise RuntimeError("Source sync executor does not support state flush")
        loop = self._loop
        if loop is None:
            raise RuntimeError("Source sync executor loop is not running")
        future = asyncio.run_coroutine_threadsafe(
            self._flush_source_state_on_executor(source_name, connection_id=connection_id),
            loop,
        )
        return await asyncio.wrap_future(future)

    async def _flush_source_state_on_executor(self, source_name: str, *, connection_id: str) -> dict[str, Any]:
        if self._flush_state is None:
            raise RuntimeError("Source sync executor does not support state flush")
        return await self._run_with_execution_lock(self._run_on_owner_loop(self._flush_state(source_name, connection_id=connection_id)))

    async def _run_with_execution_lock(
        self,
        coro: Awaitable[_ResultT],
    ) -> _ResultT:
        execution_lock = self._execution_lock
        if execution_lock is None:
            raise RuntimeError("Source sync executor execution lock is not initialized")
        async with execution_lock:
            return await coro

    async def _run_on_owner_loop(
        self,
        awaitable: Awaitable[_ResultT],
    ) -> _ResultT:
        owner_loop = self._owner_loop
        if owner_loop is None:
            raise RuntimeError("Source sync executor owner loop is not initialized")
        future = asyncio.run_coroutine_threadsafe(
            self._await_value(awaitable),
            owner_loop,
        )
        return await asyncio.wrap_future(future)

    @staticmethod
    async def _await_value(awaitable: Awaitable[_ResultT]) -> _ResultT:
        return await awaitable
