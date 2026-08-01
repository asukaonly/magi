"""Unified APScheduler-backed runtime service."""
from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler, run_in_event_loop
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine, event

from ..core.container import get_container
from ..core.logger import get_logger
from .contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from .repository import ScheduleRepository

logger = get_logger("magi.scheduler.service")

ScheduleHandler = Callable[[ScheduledExecutionContext], Awaitable[ScheduledExecutionResult]]
_T = TypeVar("_T")
_BUSY_ONCE_RETRY_METADATA_KEY = "_busy_once_retry_count"
_BUSY_ONCE_MAX_RETRY_DELAY_SECONDS = 30.0


class SchedulerDataClearInProgressError(RuntimeError):
    """Raised when scheduler work crosses a data-clear boundary."""


@dataclasses.dataclass(slots=True)
class _ExecutionPrep:
    """Shared output of the prep phase between sync + async execute paths.

    Either ``early_result`` is set (short-circuit; caller returns it as-is)
    OR the remaining fields are populated for the handler phase.
    """

    early_result: ScheduledExecutionResult | None = None
    schedule: ScheduleDefinition | None = None
    state: Any = None
    execution_id: str = ""
    effective_manual: bool = False
    started_at: float = 0.0
    data_generation: int = 0


async def dispatch_scheduled_job(schedule_id: str) -> None:
    """Module-level APScheduler entrypoint for persisted jobs."""

    try:
        service = _get_scheduler_service()
    except RuntimeError:
        return
    await service.execute_schedule(schedule_id)


def _get_scheduler_service():
    provider = get_container().scheduler_service
    instance = provider()
    if instance is None:
        raise RuntimeError("scheduler_service binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError("scheduler_service binding is not initialized")
    return instance


class ResilientAsyncIOScheduler(AsyncIOScheduler):
    """AsyncIOScheduler that retries after transient wakeup failures."""

    @run_in_event_loop
    def wakeup(self):
        self._stop_timer()
        try:
            wait_seconds = self._process_jobs()
        except Exception:
            self._logger.exception(
                "Scheduler wakeup failed; retrying after %s seconds",
                self.jobstore_retry_interval,
            )
            wait_seconds = max(float(self.jobstore_retry_interval), 0.0)
        self._start_timer(wait_seconds)


class SchedulerService:
    """Unified scheduler facade over APScheduler and repository state."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        runtime_dir: str | Path,
        repository: ScheduleRepository | None = None,
    ) -> None:
        self._db_path = Path(db_path).expanduser()
        self._runtime_dir = Path(runtime_dir).expanduser()
        self._repository = repository or ScheduleRepository(self._db_path)
        self._handlers: dict[ScheduledTargetType, ScheduleHandler] = {}
        self._schedule_lock = asyncio.Lock()
        self._data_clear_lock = asyncio.Lock()
        self._data_clear_active = False
        self._data_generation = 0
        self._active_user_execution_tasks: set[asyncio.Task[Any]] = set()
        # Strong references to background-execution tasks spawned by
        # execute_schedule_async — without this, asyncio may GC pending
        # tasks before their handlers finish. Removed via done_callback.
        self._background_tasks: set[asyncio.Task] = set()
        self._jobstore_engine = create_engine(
            f"sqlite:///{self._db_path}",
            connect_args={"timeout": 30, "check_same_thread": False},
        )

        @event.listens_for(self._jobstore_engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout = 30000")
            cursor.close()

        self._scheduler = ResilientAsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(engine=self._jobstore_engine)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120},
            timezone=ZoneInfo("UTC"),
        )
        self._running = False
        self._active = False

    @property
    def repository(self) -> ScheduleRepository:
        return self._repository

    async def start(self, *, paused: bool = False) -> None:
        if self._running:
            return
        await self._repository.initialize()
        await self._repository.reset_running_flags()
        self._scheduler.start(paused=paused)
        self._running = True
        self._active = not paused
        await self._restore_persisted_jobs()

    def activate(self) -> None:
        """Allow persisted jobs to run after all startup contributors are ready."""
        if not self._running:
            raise RuntimeError("Scheduler service is not started")
        if self._active:
            return
        self._scheduler.resume()
        self._active = True

    async def stop(self) -> None:
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._jobstore_engine.dispose()
        self._running = False
        self._active = False

    def register_handler(self, target_type: ScheduledTargetType, handler: ScheduleHandler) -> None:
        self._handlers[target_type] = handler

    async def schedule(self, definition: ScheduleDefinition) -> ScheduleDefinition:
        async with self._data_clear_lock:
            self._assert_schedule_mutation_admitted()
            return await self._schedule_definition(definition)

    async def _schedule_definition(
        self,
        definition: ScheduleDefinition,
    ) -> ScheduleDefinition:
        async with self._schedule_lock:
            existing = await self._repository.get_schedule(definition.schedule_id)
            if existing is not None and _same_schedule_definition(existing, definition):
                job_id = existing.job_id or existing.schedule_id
                if existing.enabled and self._scheduler.get_job(job_id) is None:
                    await self._upsert_job(existing)
                return existing
            await self._repository.upsert_schedule(definition)
            if definition.enabled:
                await self._upsert_job(definition)
            else:
                await self._unschedule_locked(definition.schedule_id)
            persisted = await self._repository.get_schedule(definition.schedule_id)
        return persisted or definition

    async def schedule_once(
        self,
        *,
        schedule_id: str,
        target_type: ScheduledTargetType,
        target_key: str,
        run_at: float,
        target_payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> ScheduleDefinition:
        return await self.schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=target_type,
                target_key=target_key,
                trigger=TriggerDefinition(TriggerType.ONCE, {"run_at": run_at}),
                target_payload=dict(target_payload),
                metadata=dict(metadata or {}),
            )
        )

    async def schedule_once_earliest(
        self,
        *,
        schedule_id: str,
        target_type: ScheduledTargetType,
        target_key: str,
        run_at: float,
        target_payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> ScheduleDefinition:
        """Atomically keep one one-off schedule at its earliest requested time."""
        definition = ScheduleDefinition(
            schedule_id=schedule_id,
            target_type=target_type,
            target_key=target_key,
            trigger=TriggerDefinition(TriggerType.ONCE, {"run_at": run_at}),
            target_payload=dict(target_payload),
            metadata=dict(metadata or {}),
        )
        async with self._data_clear_lock:
            self._assert_schedule_mutation_admitted()
            async with self._schedule_lock:
                return await self._schedule_once_earliest_locked(definition)

    async def _schedule_once_earliest_locked(
        self,
        definition: ScheduleDefinition,
    ) -> ScheduleDefinition:
        """Keep the earliest one-off definition while ``_schedule_lock`` is held."""
        schedule_id = definition.schedule_id
        run_at = float(definition.trigger.config["run_at"])
        existing = await self._repository.get_schedule(schedule_id)
        if existing is not None and existing.trigger.trigger_type is TriggerType.ONCE:
            existing_run_at = await self._repository.get_schedule_next_run_at(existing)
            if (
                existing_run_at is not None
                and existing_run_at > time.time()
                and existing_run_at <= run_at
            ):
                return existing
        if existing is not None:
            await self._unschedule_locked(schedule_id)
        await self._repository.upsert_schedule(definition)
        await self._upsert_job(definition)
        persisted = await self._repository.get_schedule(schedule_id)
        return persisted or definition

    async def schedule_interval(
        self,
        *,
        schedule_id: str,
        target_type: ScheduledTargetType,
        target_key: str,
        seconds: float,
        target_payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> ScheduleDefinition:
        return await self.schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=target_type,
                target_key=target_key,
                trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": seconds}),
                target_payload=dict(target_payload),
                metadata=dict(metadata or {}),
            )
        )

    async def schedule_cron(
        self,
        *,
        schedule_id: str,
        target_type: ScheduledTargetType,
        target_key: str,
        cron: dict[str, object],
        target_payload: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> ScheduleDefinition:
        return await self.schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=target_type,
                target_key=target_key,
                trigger=TriggerDefinition(TriggerType.CRON, dict(cron)),
                target_payload=dict(target_payload),
                metadata=dict(metadata or {}),
            )
        )

    async def trigger_now(self, schedule_id: str) -> None:
        await self.execute_schedule(schedule_id, manual=True)

    async def unschedule(
        self,
        schedule_id: str,
        *,
        target_type: ScheduledTargetType | None = None,
        target_key: str | None = None,
    ) -> None:
        async with self._schedule_lock:
            await self._unschedule_locked(
                schedule_id,
                target_type=target_type,
                target_key=target_key,
            )

    async def _unschedule_locked(
        self,
        schedule_id: str,
        *,
        target_type: ScheduledTargetType | None = None,
        target_key: str | None = None,
    ) -> None:
        schedule = await self._repository.get_schedule(schedule_id)
        job_id = schedule.job_id if schedule is not None else schedule_id
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        if schedule is not None:
            await self._repository.clear_target_schedule_binding(schedule.target_type, schedule.target_key)
            await self._repository.delete_schedule(schedule_id)
            return
        if target_type is not None and target_key is not None:
            await self._repository.clear_target_schedule_binding(target_type, target_key)

    async def execute_schedule(
        self,
        schedule_id: str,
        *,
        manual: bool = False,
        override_payload: dict[str, Any] | None = None,
    ) -> ScheduledExecutionResult:
        """Run a schedule once and block until it completes.

        ``override_payload``, when provided, is merged on top of the stored
        ``schedule.target_payload`` for this execution only — the DB row is
        not mutated, so the next scheduled tick sees the original payload.
        Use this to give a handler one-shot parameters from a manual
        trigger (e.g. ``{"days": 7}`` to backfill instead of the default 1).

        Handlers opt in by reading ``context.schedule.target_payload``;
        handlers that don't read it keep their current behavior.

        For manual triggers from HTTP endpoints (where the request
        shouldn't hang for minutes), prefer ``execute_schedule_async``.
        """
        current_task = asyncio.current_task()
        async with self._data_clear_lock:
            prep = await self._prepare_execution_locked(
                schedule_id,
                manual=manual,
                override_payload=override_payload,
            )
            tracks_user_execution = bool(
                prep.early_result is None
                and prep.schedule is not None
                and prep.schedule.target_type is ScheduledTargetType.USER_AGENT_TASK
                and current_task is not None
            )
            if tracks_user_execution:
                assert current_task is not None
                self._active_user_execution_tasks.add(current_task)
        if prep.early_result is not None:
            await self._reschedule_busy_once(schedule_id, prep.early_result)
            return prep.early_result
        try:
            return await self._run_handler_phase(
                schedule=prep.schedule,
                state=prep.state,
                execution_id=prep.execution_id,
                manual=prep.effective_manual,
                started_at=prep.started_at,
                data_generation=prep.data_generation,
            )
        finally:
            if tracks_user_execution and current_task is not None:
                async with self._data_clear_lock:
                    self._active_user_execution_tasks.discard(current_task)

    async def execute_schedule_async(
        self,
        schedule_id: str,
        *,
        manual: bool = True,
        override_payload: dict[str, Any] | None = None,
    ) -> ScheduledExecutionResult:
        """Fire-and-forget variant of execute_schedule.

        Runs the synchronous setup (lookup, lock, execution record) inline
        so the caller learns about ``schedule_not_found`` / ``target_busy``
        immediately, then spawns the handler in a background task and
        returns ``{success=True, message='queued'}`` with the execution_id.

        Used by the manual-trigger HTTP endpoint to avoid the request
        hanging for the entire handler duration (e.g. multi-day diary
        backfills that take several minutes).
        """

        async def _runner() -> None:
            try:
                await self._run_handler_phase(
                    schedule=prep.schedule,
                    state=prep.state,
                    execution_id=prep.execution_id,
                    manual=prep.effective_manual,
                    started_at=prep.started_at,
                    data_generation=prep.data_generation,
                )
            except Exception as exc:  # pragma: no cover — already recorded
                # _run_handler_phase records failure to the execution row
                # before re-raising; the re-raise is for the original sync
                # caller. In the async path the exception is logged and
                # swallowed so the asyncio loop doesn't print "Task exception
                # was never retrieved" tracebacks.
                logger.warning(
                    "background schedule execution raised", schedule_id=schedule_id, error=str(exc),
                )
            finally:
                current_task = asyncio.current_task()
                if current_task is not None:
                    async with self._data_clear_lock:
                        self._active_user_execution_tasks.discard(current_task)

        async with self._data_clear_lock:
            prep = await self._prepare_execution_locked(
                schedule_id,
                manual=manual,
                override_payload=override_payload,
            )
            if prep.early_result is not None:
                early_result = prep.early_result
            else:
                early_result = None
                task = asyncio.create_task(
                    _runner(),
                    name=f"schedule-run-{schedule_id}-{prep.execution_id}",
                )
                if (
                    prep.schedule is not None
                    and prep.schedule.target_type is ScheduledTargetType.USER_AGENT_TASK
                ):
                    self._active_user_execution_tasks.add(task)
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
        if early_result is not None:
            await self._reschedule_busy_once(schedule_id, early_result)
            return early_result

        return ScheduledExecutionResult(
            success=True,
            message="queued",
            stats={
                "execution_id": prep.execution_id,
                "status": "running",
            },
        )

    async def _reschedule_busy_once(
        self,
        schedule_id: str,
        result: ScheduledExecutionResult,
    ) -> None:
        """Keep a busy one-off target durable without leaving an orphan row."""
        if result.message != "target_busy":
            return
        async with self._data_clear_lock:
            async with self._schedule_lock:
                schedule = await self._repository.get_schedule(schedule_id)
                if schedule is None or schedule.trigger.trigger_type is not TriggerType.ONCE:
                    return
                self._assert_schedule_mutation_admitted()

                retry_count = int(schedule.metadata.get(_BUSY_ONCE_RETRY_METADATA_KEY, 0)) + 1
                delay_seconds = min(
                    _BUSY_ONCE_MAX_RETRY_DELAY_SECONDS,
                    2.0 ** min(max(0, retry_count - 1), 5),
                )
                replacement = dataclasses.replace(
                    schedule,
                    trigger=TriggerDefinition(
                        TriggerType.ONCE,
                        {"run_at": time.time() + delay_seconds},
                    ),
                    metadata={
                        **schedule.metadata,
                        _BUSY_ONCE_RETRY_METADATA_KEY: retry_count,
                    },
                )
                await self._schedule_once_earliest_locked(replacement)

    async def _prepare_execution_locked(
        self,
        schedule_id: str,
        *,
        manual: bool,
        override_payload: dict[str, Any] | None,
    ) -> "_ExecutionPrep":
        """Prepare an execution while the data-clear admission lock is held."""
        schedule, early_result = await self._load_execution_schedule(
            schedule_id,
            override_payload=override_payload,
        )
        if early_result is not None:
            return early_result
        assert schedule is not None
        if self._data_clear_active:
            return self._early_execution_prep("data_clear_in_progress")

        effective_manual = manual or bool(schedule.metadata.get("manual", False))
        started_at = time.time()
        if schedule.target_type is ScheduledTargetType.SENSOR_SYNC:
            return await self._prepare_sensor_sync_execution(
                schedule=schedule,
                effective_manual=effective_manual,
                started_at=started_at,
            )

        started_at, early_result = await self._acquire_execution_lock(schedule)
        if early_result is not None:
            return early_result

        execution_id = await self._repository.create_execution_record(
            schedule_id=schedule.schedule_id,
            target_type=schedule.target_type,
            target_key=schedule.target_key,
            manual=effective_manual,
            started_at=started_at,
        )

        return await self._prepare_handler_execution(
            schedule=schedule,
            execution_id=execution_id,
            effective_manual=effective_manual,
            started_at=started_at,
            data_generation=self._data_generation,
        )

    async def _prepare_handler_execution(
        self,
        *,
        schedule: ScheduleDefinition,
        execution_id: str,
        effective_manual: bool,
        started_at: float,
        data_generation: int,
    ) -> _ExecutionPrep:
        state = await self._repository.get_target_state(
            schedule.target_type,
            schedule.target_key,
        )
        return _ExecutionPrep(
            schedule=schedule,
            state=state,
            execution_id=execution_id,
            effective_manual=effective_manual,
            started_at=started_at,
            data_generation=data_generation,
        )

    async def _load_execution_schedule(
        self,
        schedule_id: str,
        *,
        override_payload: dict[str, Any] | None,
    ) -> tuple[ScheduleDefinition | None, _ExecutionPrep | None]:
        schedule = await self._repository.get_schedule(schedule_id)
        if schedule is None:
            return None, self._early_execution_prep("schedule_not_found")
        if override_payload:
            schedule = dataclasses.replace(
                schedule,
                target_payload={**schedule.target_payload, **override_payload},
            )
        return schedule, None

    async def _acquire_execution_lock(
        self,
        schedule: ScheduleDefinition,
    ) -> tuple[float, _ExecutionPrep | None]:
        started_at = time.time()
        acquired = await self._repository.acquire_target_lock(
            schedule.target_type,
            schedule.target_key,
        )
        if acquired:
            return started_at, None
        return started_at, self._early_execution_prep("target_busy")

    async def _prepare_sensor_sync_execution(
        self,
        *,
        schedule: ScheduleDefinition,
        effective_manual: bool,
        started_at: float,
    ) -> _ExecutionPrep:
        # SENSOR_SYNC has its own enqueue-and-return path so the sync caller
        # still gets the "sensor_sync_enqueued" reply.
        admitted = await self._repository.enqueue_sensor_sync_execution(
            schedule=schedule,
            manual=effective_manual,
            started_at=started_at,
        )
        if admitted is None:
            return self._early_execution_prep("target_busy")
        if schedule.trigger.trigger_type == TriggerType.ONCE:
            await self._repository.delete_schedule(schedule.schedule_id)
        return self._early_execution_prep(
            "sensor_sync_enqueued",
            success=True,
            stats={
                "job_id": admitted.job_id,
                "execution_id": admitted.execution_id,
            },
        )

    @staticmethod
    def _early_execution_prep(
        message: str,
        *,
        success: bool = False,
        stats: dict[str, Any] | None = None,
    ) -> _ExecutionPrep:
        return _ExecutionPrep(
            early_result=ScheduledExecutionResult(
                success=success,
                message=message,
                stats=stats or {},
            )
        )

    async def _run_handler_phase(
        self,
        *,
        schedule,
        state,
        execution_id: str,
        manual: bool,
        started_at: float,
        data_generation: int,
    ) -> ScheduledExecutionResult:
        """Call the handler and record success/failure on the execution row.

        Re-raises the original exception so callers running synchronously
        can propagate it (e.g. ``trigger_now`` test asserts on the raise).
        """
        handler = self._handlers.get(schedule.target_type)
        try:
            if handler is None:
                raise RuntimeError(f"Unhandled schedule target: {schedule.target_type.value}")
            result = await handler(
                ScheduledExecutionContext(
                    schedule=schedule,
                    target_state=state,
                    runtime_dir=self._runtime_dir,
                    triggered_at=started_at,
                    manual=manual,
                    data_generation=data_generation,
                )
            )
            async with self._data_clear_lock:
                await self._assert_execution_settlement_current(
                    schedule,
                    data_generation,
                )
                await self._repository.record_target_success(
                    schedule.target_type,
                    schedule.target_key,
                    result=result,
                    scheduler_job_id=schedule.job_id or schedule.schedule_id,
                )
                await self._repository.complete_execution_success(
                    execution_id,
                    result=result,
                    scheduler_job_id=schedule.job_id or schedule.schedule_id,
                    finished_at=time.time(),
                )
            if schedule.trigger.trigger_type == TriggerType.ONCE:
                await self._consume_once_schedule(schedule)
            return result
        except Exception as exc:
            async with self._data_clear_lock:
                await self._assert_execution_settlement_current(
                    schedule,
                    data_generation,
                )
                await self._repository.record_target_failure(
                    schedule.target_type,
                    schedule.target_key,
                    error=str(exc),
                    scheduler_job_id=schedule.job_id or schedule.schedule_id,
                )
                await self._repository.complete_execution_failure(
                    execution_id,
                    error=str(exc),
                    scheduler_job_id=schedule.job_id or schedule.schedule_id,
                    finished_at=time.time(),
                )
            if schedule.trigger.trigger_type == TriggerType.ONCE:
                await self._consume_once_schedule(schedule)
            raise

    @asynccontextmanager
    async def user_data_clear_boundary(self) -> AsyncIterator[None]:
        """Seal scheduler execution and retire stale user-task handlers."""

        current_task = asyncio.current_task()
        async with self._data_clear_lock:
            if self._data_clear_active:
                raise RuntimeError("Scheduler data clear is already in progress")
            self._data_clear_active = True
            self._data_generation += 1
            stale_tasks = [
                task
                for task in self._active_user_execution_tasks
                if task is not current_task and not task.done()
            ]
        try:
            for task in stale_tasks:
                task.cancel()
            if stale_tasks:
                await asyncio.gather(*stale_tasks, return_exceptions=True)
            yield
        finally:
            async with self._data_clear_lock:
                self._data_clear_active = False

    async def clear_user_data(self) -> dict[str, int]:
        """Delete scheduler-owned user content inside the clear boundary."""

        async with self._data_clear_lock:
            if not self._data_clear_active:
                raise RuntimeError("Scheduler user data clear requires an active clear boundary")
        async with self._schedule_lock:
            user_schedules = [
                schedule
                for schedule in await self._repository.list_schedules(enabled_only=False)
                if schedule.target_type is ScheduledTargetType.USER_AGENT_TASK
            ]
            for schedule in user_schedules:
                try:
                    self._scheduler.remove_job(schedule.job_id or schedule.schedule_id)
                except Exception:
                    pass
            return await self._repository.clear_user_data()

    async def run_user_agent_effect(
        self,
        data_generation: int,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Commit one user-agent side effect only in its admitted generation."""

        async with self._data_clear_lock:
            self._assert_execution_generation(data_generation)
            return await operation()

    def _assert_schedule_mutation_admitted(self) -> None:
        if self._data_clear_active:
            raise SchedulerDataClearInProgressError("Scheduler data clear is in progress")

    def _assert_execution_generation(self, data_generation: int) -> None:
        if self._data_clear_active or data_generation != self._data_generation:
            raise SchedulerDataClearInProgressError(
                "Scheduled execution crossed a user data clear boundary"
            )

    async def _assert_execution_settlement_current(
        self,
        schedule: ScheduleDefinition,
        data_generation: int,
    ) -> None:
        try:
            self._assert_execution_generation(data_generation)
        except SchedulerDataClearInProgressError:
            await self._repository.release_target_after_data_clear(
                schedule.target_type,
                schedule.target_key,
            )
            raise

    async def _consume_once_schedule(self, executed: ScheduleDefinition) -> None:
        """Delete only the exact one-off definition that just finished.

        A handler may schedule the same identifier for a future retry before it
        returns.  In that case the replacement must survive completion of the
        currently executing definition.
        """
        async with self._schedule_lock:
            current = await self._repository.get_schedule(executed.schedule_id)
            if current is None or not _same_once_trigger(current, executed):
                return
            try:
                self._scheduler.remove_job(current.job_id or current.schedule_id)
            except Exception:
                pass
            await self._repository.delete_schedule(executed.schedule_id)

    async def get_target_state(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ):
        return await self._repository.get_target_state(target_type, target_key)

    async def update_target_cursor(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
        *,
        cursor: str,
        watermark_ts: float | None = None,
    ) -> None:
        """Persist a partial cursor checkpoint during batch ingestion."""
        await self._repository.update_target_cursor(
            target_type, target_key, cursor=cursor, watermark_ts=watermark_ts,
        )

    async def _restore_persisted_jobs(self) -> None:
        async with self._schedule_lock:
            for schedule in await self._repository.list_schedules(enabled_only=True):
                await self._upsert_job(schedule)

    async def _upsert_job(self, schedule: ScheduleDefinition) -> None:
        trigger = self._build_trigger(schedule.trigger)
        job_id = schedule.job_id or schedule.schedule_id
        # Preserve an already-scheduled job's next_run across re-registration.
        # _upsert_job runs on every app start (via _restore_persisted_jobs and the
        # contribs' register_schedules). Without this, an INTERVAL trigger recomputes
        # next_run = now + interval each time, so a long-interval job (e.g. 24h L2
        # maintenance) is perpetually reset on a desktop app that restarts more often
        # than the interval, and never fires (#85). The persistent jobstore already
        # holds the live next_run after start(); reuse it instead of resetting.
        # misfire_grace_time=None makes a run that came due while the app was down
        # fire as catch-up on the next start (coalesce=True collapses multiple missed
        # runs into one) instead of being skipped — on a desktop app the exact
        # interval window is rarely hit, so the default 120s grace would drop the run
        # until the next full interval.
        add_kwargs: dict[str, object] = {}
        existing = self._scheduler.get_job(job_id)
        if existing is not None and existing.next_run_time is not None:
            add_kwargs["next_run_time"] = existing.next_run_time
        job = self._scheduler.add_job(
            dispatch_scheduled_job,
            trigger=trigger,
            id=job_id,
            args=[schedule.schedule_id],
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
            **add_kwargs,
        )
        await self._repository.update_schedule_binding(
            schedule.schedule_id,
            job_id=job.id,
        )

    def _build_trigger(self, trigger: TriggerDefinition):
        if trigger.trigger_type == TriggerType.ONCE:
            return DateTrigger(run_date=self._coerce_datetime(trigger.config.get("run_at")))
        if trigger.trigger_type == TriggerType.INTERVAL:
            return IntervalTrigger(seconds=float(trigger.config.get("seconds", 60.0)))
        if trigger.trigger_type == TriggerType.CRON:
            return CronTrigger(**trigger.config)
        raise ValueError(f"Unsupported trigger type: {trigger.trigger_type}")

    @staticmethod
    def _coerce_datetime(value: object):
        from datetime import datetime, timezone

        if isinstance(value, datetime):
            return value
        return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _same_once_trigger(left: ScheduleDefinition, right: ScheduleDefinition) -> bool:
    """Return whether two definitions represent the same one-off firing."""
    return (
        left.trigger.trigger_type is TriggerType.ONCE
        and right.trigger.trigger_type is TriggerType.ONCE
        and left.trigger.config == right.trigger.config
    )


def _same_schedule_definition(
    left: ScheduleDefinition,
    right: ScheduleDefinition,
) -> bool:
    """Return whether persisting ``right`` would leave the schedule unchanged."""
    return (
        left.schedule_id == right.schedule_id
        and left.target_type is right.target_type
        and left.target_key == right.target_key
        and left.trigger == right.trigger
        and left.target_payload == right.target_payload
        and left.enabled == right.enabled
        and left.metadata == right.metadata
        and (left.job_id or left.schedule_id) == (right.job_id or right.schedule_id)
    )
