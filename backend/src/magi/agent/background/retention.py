"""Scheduler-owned retention cleanup for background-task history."""

from __future__ import annotations

import time
from typing import Any, Callable

import structlog

from ...config import get_config
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from .store import BackgroundTaskStore

__all__ = [
    "BACKGROUND_TASK_RETENTION_INTERVAL_SECONDS",
    "BackgroundTaskRetentionScheduleContrib",
    "SCHEDULE_ID_BACKGROUND_TASK_RETENTION",
    "TARGET_KEY_BACKGROUND_TASK_RETENTION",
]


logger = structlog.get_logger(__name__)

BACKGROUND_TASK_RETENTION_INTERVAL_SECONDS = 3600.0
SCHEDULE_ID_BACKGROUND_TASK_RETENTION = "background-task-retention:global"
TARGET_KEY_BACKGROUND_TASK_RETENTION = "background_task_retention"


class BackgroundTaskRetentionScheduleContrib:
    """Register background-task history retention with the persistent scheduler."""

    def __init__(
        self,
        *,
        store: BackgroundTaskStore,
        get_config_func: Callable[[], Any] = get_config,
    ) -> None:
        self._store = store
        self._get_config = get_config_func

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(
            ScheduledTargetType.BACKGROUND_TASK_RETENTION,
            self.handle,
        )
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_BACKGROUND_TASK_RETENTION,
            target_type=ScheduledTargetType.BACKGROUND_TASK_RETENTION,
            target_key=TARGET_KEY_BACKGROUND_TASK_RETENTION,
            seconds=BACKGROUND_TASK_RETENTION_INTERVAL_SECONDS,
            target_payload={},
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_BACKGROUND_TASK_RETENTION,
            target_type=ScheduledTargetType.BACKGROUND_TASK_RETENTION,
            target_key=TARGET_KEY_BACKGROUND_TASK_RETENTION,
        )

    async def handle(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        config = self._get_config()
        retention_days = float(config.agent.background_tasks.history_retention_days)
        retention_seconds = max(retention_days, 0.0) * 86_400.0
        now = float(getattr(context, "triggered_at", 0.0) or time.time())
        try:
            deleted = await self._store.purge_expired(
                retention_seconds=retention_seconds,
                now=now,
            )
        except Exception as exc:
            logger.warning("background task retention failed", error=str(exc), exc_info=True)
            return ScheduledExecutionResult(
                success=False,
                message="background_task_retention_failed",
                stats={"error": str(exc)},
            )
        return ScheduledExecutionResult(
            success=True,
            message="background_task_retention_ok",
            stats={"background_tasks_deleted": deleted},
        )
