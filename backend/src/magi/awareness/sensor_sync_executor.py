"""Dedicated queued executor for pull-based sensor sync jobs."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Awaitable, Callable

from ..core.logger import get_logger
from ..scheduler.contracts import ScheduledExecutionResult, ScheduledTargetType
from ..scheduler.repository import ScheduleRepository

logger = get_logger(__name__)

SensorSyncJobRunner = Callable[[dict[str, object]], Awaitable[ScheduledExecutionResult]]
SensorStateFlushRunner = Callable[[str], Awaitable[dict[str, Any]]]


class SensorSyncExecutor:
    """Run queued sensor sync jobs on a dedicated thread-local event loop."""

    def __init__(
        self,
        *,
        repository: ScheduleRepository,
        run_job: SensorSyncJobRunner,
        flush_state: SensorStateFlushRunner | None = None,
        poll_interval_seconds: float = 0.1,
        running_timeout_seconds: float = 1800.0,
        worker_id: str = "sensor-sync-executor",
    ) -> None:
        self._repository = repository
        self._run_job = run_job
        self._flush_state = flush_state
        self._poll_interval_seconds = poll_interval_seconds
        self._running_timeout_seconds = running_timeout_seconds
        self._worker_id = worker_id
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._execution_lock: asyncio.Lock | None = None
        self._ready = threading.Event()

    async def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._owner_loop = asyncio.get_running_loop()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_thread,
            name=self._worker_id,
            daemon=True,
        )
        self._thread.start()
        ready = await asyncio.to_thread(self._ready.wait, 5.0)
        if not ready:
            raise RuntimeError("Timed out starting sensor sync executor thread")

    async def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        loop = self._loop
        stop_event = self._stop_event
        if loop is not None and stop_event is not None:
            loop.call_soon_threadsafe(stop_event.set)
        await asyncio.to_thread(thread.join, 5.0)
        self._thread = None
        self._owner_loop = None

    def _run_thread(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop_event = asyncio.Event()
        self._execution_lock = asyncio.Lock()
        self._ready.set()
        try:
            loop.run_until_complete(self._run_loop())
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                self._loop = None
                self._stop_event = None
                self._execution_lock = None

    async def _run_loop(self) -> None:
        await self._repository.requeue_stale_sensor_sync_jobs(
            running_timeout_seconds=self._running_timeout_seconds,
        )
        stop_event = self._stop_event
        if stop_event is None:
            raise RuntimeError("Sensor sync executor stop event was not initialized")

        while not stop_event.is_set():
            try:
                job = await self._repository.claim_next_sensor_sync_job(claimed_by=self._worker_id)
                if job is None:
                    await self._wait_for_next_poll(stop_event)
                    continue
                await self._execute_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Sensor sync executor loop failed", error=str(exc))
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
        execution_id = str(job["execution_id"])
        scheduler_binding = await self._repository.get_recurring_target_binding(target_type, target_key)
        scheduler_job_id = str(scheduler_binding[0]) if scheduler_binding is not None else None
        next_run_at = float(scheduler_binding[1]) if scheduler_binding is not None and scheduler_binding[1] is not None else None

        try:
            result = await self._run_with_execution_lock(self._run_on_owner_loop(self._run_job(job)))
            if not result.success:
                raise RuntimeError(result.message or "sensor_sync_failed")
            finished_at = time.time()
            await self._repository.complete_sensor_sync_job_success(
                str(job["job_id"]),
                result=result,
                finished_at=finished_at,
            )
            await self._repository.record_target_success(
                target_type,
                target_key,
                result=result,
                next_run_at=next_run_at,
                scheduler_job_id=scheduler_job_id,
            )
            await self._repository.complete_execution_success(
                execution_id,
                result=result,
                scheduler_job_id=scheduler_job_id,
                finished_at=finished_at,
            )
        except Exception as exc:
            finished_at = time.time()
            await self._repository.complete_sensor_sync_job_failure(
                str(job["job_id"]),
                error=str(exc),
                finished_at=finished_at,
            )
            await self._repository.record_target_failure(
                target_type,
                target_key,
                error=str(exc),
                next_run_at=next_run_at,
                scheduler_job_id=scheduler_job_id,
            )
            await self._repository.complete_execution_failure(
                execution_id,
                error=str(exc),
                scheduler_job_id=scheduler_job_id,
                finished_at=finished_at,
            )

    async def flush_sensor_state(self, source_name: str) -> dict[str, Any]:
        if self._flush_state is None:
            raise RuntimeError("Sensor sync executor does not support state flush")
        loop = self._loop
        if loop is None:
            raise RuntimeError("Sensor sync executor loop is not running")
        future = asyncio.run_coroutine_threadsafe(
            self._flush_sensor_state_on_executor(source_name),
            loop,
        )
        return await asyncio.wrap_future(future)

    async def _flush_sensor_state_on_executor(self, source_name: str) -> dict[str, Any]:
        if self._flush_state is None:
            raise RuntimeError("Sensor sync executor does not support state flush")
        return await self._run_with_execution_lock(self._run_on_owner_loop(self._flush_state(source_name)))

    async def _run_with_execution_lock(self, coro: Awaitable[Any]) -> Any:
        execution_lock = self._execution_lock
        if execution_lock is None:
            raise RuntimeError("Sensor sync executor execution lock is not initialized")
        async with execution_lock:
            return await coro

    async def _run_on_owner_loop(self, coro: Awaitable[Any]) -> Any:
        owner_loop = self._owner_loop
        if owner_loop is None:
            raise RuntimeError("Sensor sync executor owner loop is not initialized")
        future = asyncio.run_coroutine_threadsafe(coro, owner_loop)
        return await asyncio.wrap_future(future)
