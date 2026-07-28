"""Dedicated queued executor for pull-based sensor sync jobs."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
import uuid
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from ..core.logger import get_logger
from ..scheduler.contracts import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ..scheduler.repository import ScheduleRepository

logger = get_logger(__name__)

SensorSyncJobRunner = Callable[[dict[str, object]], Awaitable[ScheduledExecutionResult]]
SensorStateFlushRunner = Callable[[str], Awaitable[dict[str, Any]]]
_ResultT = TypeVar("_ResultT")

_POST_SYNC_L3_BACKFILL_MAX_PERIODS = 4


class SensorSyncScheduler(Protocol):
    """Scheduler operations used after a sensor job commits."""

    async def schedule_once(
        self,
        *,
        schedule_id: str,
        target_type: ScheduledTargetType,
        target_key: str,
        run_at: float,
        target_payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> ScheduleDefinition: ...

    async def execute_schedule_async(
        self,
        schedule_id: str,
        *,
        manual: bool = True,
        override_payload: dict[str, Any] | None = None,
    ) -> ScheduledExecutionResult: ...


class SensorSyncExecutor:
    """Run queued sensor sync jobs on a dedicated thread-local event loop."""

    def __init__(
        self,
        *,
        repository: ScheduleRepository,
        run_job: SensorSyncJobRunner,
        flush_state: SensorStateFlushRunner | None = None,
        scheduler_service: SensorSyncScheduler | None = None,
        poll_interval_seconds: float = 0.1,
        max_attempts: int = 4,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 300.0,
        worker_id: str = "sensor-sync-executor",
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
        self._worker_id = worker_id
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._execution_lock: asyncio.Lock | None = None
        self._post_sync_lock = threading.Lock()
        self._post_sync_sources: set[str] = set()
        self._post_sync_future: concurrent.futures.Future[None] | None = None
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
        post_sync_future = self._clear_post_sync_queue()
        if post_sync_future is not None and not post_sync_future.done():
            post_sync_future.cancel()
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
        await self._repository.recover_running_sensor_sync_jobs()
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
                try:
                    await self._repository.recover_running_sensor_sync_jobs()
                except Exception:
                    logger.exception("Sensor sync executor could not recover running jobs")
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
                raise RuntimeError(result.message or "sensor_sync_failed")
        except Exception as exc:
            await self._settle_failed_job(
                job,
                scheduler_job_id=scheduler_job_id,
                error=exc,
            )
            return

        finished_at = time.time()
        try:
            await self._repository.settle_sensor_sync_job_success(
                str(job["job_id"]),
                result=result,
                finished_at=finished_at,
                scheduler_job_id=scheduler_job_id,
            )
        except Exception as exc:
            persisted = await self._repository.get_sensor_sync_job(str(job["job_id"]))
            if persisted is None or persisted.get("status") != "success":
                await self._settle_failed_job(
                    job,
                    scheduler_job_id=scheduler_job_id,
                    error=exc,
                )
                return
            logger.warning(
                "Sensor sync success commit returned an error after persistence",
                job_id=str(job["job_id"]),
                error=str(exc),
            )

        continuation_queued = False
        if self._result_requests_continuation(result) and not self._job_disables_continuation(job):
            continuation_queued = await self._schedule_sync_continuation(job)
        if not continuation_queued:
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
        requeued = await self._repository.settle_sensor_sync_job_failure(
            str(job["job_id"]),
            error=str(error),
            failed_at=finished_at,
            retry_delay_seconds=retry_delay_seconds,
            max_attempts=self._max_attempts,
            scheduler_job_id=scheduler_job_id,
        )
        if requeued:
            logger.warning(
                "Sensor sync scheduled for retry",
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

    async def _schedule_sync_continuation(self, job: dict[str, object]) -> bool:
        if self._scheduler_service is None:
            return False
        plugin_id = str(job.get("plugin_id") or "").strip()
        source_type = str(job.get("source_type") or "").strip()
        if not plugin_id or not source_type:
            return False
        parent_payload = job.get("payload")
        sync_request = None
        if isinstance(parent_payload, dict) and isinstance(parent_payload.get("sync_request"), dict):
            sync_request = dict(parent_payload["sync_request"])
        target_payload: dict[str, object] = {
            "plugin_id": plugin_id,
            "source_type": source_type,
            "manual": bool(job.get("manual")),
        }
        metadata: dict[str, object] = {
            "continuation": True,
            "plugin_id": plugin_id,
            "source_type": source_type,
            "parent_job_id": str(job.get("job_id") or ""),
        }
        if sync_request is not None:
            target_payload["sync_request"] = sync_request
            metadata["sync_request"] = sync_request
        try:
            await self._run_on_owner_loop(
                self._scheduler_service.schedule_once(
                    schedule_id=(
                        f"sensor-sync-continuation:{plugin_id}:{source_type}:"
                        f"{uuid.uuid4().hex}"
                    ),
                    target_type=ScheduledTargetType.SENSOR_SYNC,
                    target_key=str(job["target_key"]),
                    run_at=time.time() + 0.2,
                    target_payload=target_payload,
                    metadata=metadata,
                )
            )
            return True
        except Exception:
            logger.exception(
                "sensor sync continuation scheduling failed (non-fatal)",
                plugin_id=plugin_id,
                source_type=source_type,
            )
            return False

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
                # outside the serial sensor executor so slow LLM calls cannot stop
                # later sensor sync jobs from being claimed.
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
                "L3 backfill after sensor sync",
                source=source_name,
                generated=len(backfilled.get("generated", [])),
                skipped_existing=backfilled.get("skipped_existing", 0),
                skipped_sparse=backfilled.get("skipped_sparse", 0),
            )
        except Exception:  # pragma: no cover - defensive: L3 must never fail a sync
            logger.exception(
                "L3 backfill after sensor sync failed (non-fatal)",
                source=source_name,
            )

    async def _trigger_l2_derive_after_sync(self) -> None:
        """Best-effort: kick the L2 derive task so a just-synced sensor's interests/
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

    async def _run_with_execution_lock(
        self,
        coro: Awaitable[_ResultT],
    ) -> _ResultT:
        execution_lock = self._execution_lock
        if execution_lock is None:
            raise RuntimeError("Sensor sync executor execution lock is not initialized")
        async with execution_lock:
            return await coro

    async def _run_on_owner_loop(
        self,
        awaitable: Awaitable[_ResultT],
    ) -> _ResultT:
        owner_loop = self._owner_loop
        if owner_loop is None:
            raise RuntimeError("Sensor sync executor owner loop is not initialized")
        future = asyncio.run_coroutine_threadsafe(
            self._await_value(awaitable),
            owner_loop,
        )
        return await asyncio.wrap_future(future)

    @staticmethod
    async def _await_value(awaitable: Awaitable[_ResultT]) -> _ResultT:
        return await awaitable
