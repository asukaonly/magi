"""Unified APScheduler-backed runtime service."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine, event

from .contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from .repository import ScheduleRepository

ScheduleHandler = Callable[[ScheduledExecutionContext], Awaitable[ScheduledExecutionResult]]

_active_scheduler_service: "SchedulerService | None" = None


async def dispatch_scheduled_job(schedule_id: str) -> None:
    """Module-level APScheduler entrypoint for persisted jobs."""

    service = get_active_scheduler_service()
    if service is None:
        return
    await service.execute_schedule(schedule_id)


def get_active_scheduler_service() -> "SchedulerService | None":
    """Return the active scheduler service when initialized."""

    return _active_scheduler_service


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

        self._scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(engine=self._jobstore_engine)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120},
            timezone=ZoneInfo("UTC"),
        )
        self._running = False

    @property
    def repository(self) -> ScheduleRepository:
        return self._repository

    async def start(self) -> None:
        global _active_scheduler_service
        if self._running:
            return
        await self._repository.initialize()
        await self._repository.reset_running_flags()
        self._scheduler.start()
        _active_scheduler_service = self
        self._running = True
        await self._restore_persisted_jobs()

    async def stop(self) -> None:
        global _active_scheduler_service
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._jobstore_engine.dispose()
        self._running = False
        if _active_scheduler_service is self:
            _active_scheduler_service = None

    def register_handler(self, target_type: ScheduledTargetType, handler: ScheduleHandler) -> None:
        self._handlers[target_type] = handler

    async def schedule(self, definition: ScheduleDefinition) -> ScheduleDefinition:
        async with self._schedule_lock:
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

    async def unschedule(self, schedule_id: str) -> None:
        async with self._schedule_lock:
            await self._unschedule_locked(schedule_id)

    async def _unschedule_locked(self, schedule_id: str) -> None:
        schedule = await self._repository.get_schedule(schedule_id)
        job_id = schedule.job_id if schedule is not None else schedule_id
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        if schedule is not None:
            await self._repository.clear_target_schedule_binding(schedule.target_type, schedule.target_key)
            await self._repository.delete_schedule(schedule_id)

    async def execute_schedule(self, schedule_id: str, *, manual: bool = False) -> ScheduledExecutionResult:
        schedule = await self._repository.get_schedule(schedule_id)
        if schedule is None:
            return ScheduledExecutionResult(success=False, message="schedule_not_found")
        acquired = await self._repository.acquire_target_lock(schedule.target_type, schedule.target_key)
        if not acquired:
            return ScheduledExecutionResult(success=False, message="target_busy")
        state = await self._repository.get_target_state(schedule.target_type, schedule.target_key)
        handler = self._handlers.get(schedule.target_type)
        try:
            if handler is None:
                raise RuntimeError(f"Unhandled schedule target: {schedule.target_type.value}")
            result = await handler(
                ScheduledExecutionContext(
                    schedule=schedule,
                    target_state=state,
                    runtime_dir=self._runtime_dir,
                    triggered_at=time.time(),
                    manual=manual or bool(schedule.metadata.get("manual", False)),
                )
            )
            next_run_at = self._resolve_next_run_time(schedule.job_id or schedule.schedule_id)
            await self._repository.record_target_success(
                schedule.target_type,
                schedule.target_key,
                result=result,
                next_run_at=next_run_at,
                scheduler_job_id=schedule.job_id or schedule.schedule_id,
            )
            if schedule.trigger.trigger_type == TriggerType.ONCE:
                await self._repository.delete_schedule(schedule.schedule_id)
            return result
        except Exception as exc:
            next_run_at = self._resolve_next_run_time(schedule.job_id or schedule.schedule_id)
            await self._repository.record_target_failure(
                schedule.target_type,
                schedule.target_key,
                error=str(exc),
                next_run_at=next_run_at,
                scheduler_job_id=schedule.job_id or schedule.schedule_id,
            )
            if schedule.trigger.trigger_type == TriggerType.ONCE:
                await self._repository.delete_schedule(schedule.schedule_id)
            raise

    async def get_target_state(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ):
        return await self._repository.get_target_state(target_type, target_key)

    async def _restore_persisted_jobs(self) -> None:
        async with self._schedule_lock:
            for schedule in await self._repository.list_schedules(enabled_only=True):
                await self._upsert_job(schedule)

    async def _upsert_job(self, schedule: ScheduleDefinition) -> None:
        trigger = self._build_trigger(schedule.trigger)
        job_id = schedule.job_id or schedule.schedule_id
        job = self._scheduler.add_job(
            dispatch_scheduled_job,
            trigger=trigger,
            id=job_id,
            args=[schedule.schedule_id],
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        await self._repository.update_schedule_binding(
            schedule.schedule_id,
            job_id=job.id,
            next_run_at=job.next_run_time.timestamp() if job.next_run_time else None,
        )

    def _build_trigger(self, trigger: TriggerDefinition):
        if trigger.trigger_type == TriggerType.ONCE:
            return DateTrigger(run_date=self._coerce_datetime(trigger.config.get("run_at")))
        if trigger.trigger_type == TriggerType.INTERVAL:
            return IntervalTrigger(seconds=float(trigger.config.get("seconds", 60.0)))
        if trigger.trigger_type == TriggerType.CRON:
            return CronTrigger(**trigger.config)
        raise ValueError(f"Unsupported trigger type: {trigger.trigger_type}")

    def _resolve_next_run_time(self, job_id: str | None) -> Optional[float]:
        if not job_id:
            return None
        job = self._scheduler.get_job(job_id)
        if job is None or job.next_run_time is None:
            return None
        return job.next_run_time.timestamp()

    @staticmethod
    def _coerce_datetime(value: object):
        from datetime import datetime, timezone

        if isinstance(value, datetime):
            return value
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
