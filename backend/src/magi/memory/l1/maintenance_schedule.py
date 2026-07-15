"""Scheduler integration for periodic L1 retention maintenance."""

from __future__ import annotations

from ...config import get_config
from ...core.logger import get_logger
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from ..provider import get_unified_memory

logger = get_logger(__name__)


SCHEDULE_ID_L1_MAINTENANCE = "memory-l1-maintenance:global"
TARGET_KEY_L1_MAINTENANCE = "memory_l1_maintenance"


async def handle_l1_maintenance(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Run L1 retention cleanup independently from global runtime maintenance."""
    _ = context
    memory_cfg = get_config().agent.memory
    l1_cfg = memory_cfg.l1
    if not l1_cfg.enabled:
        return ScheduledExecutionResult(success=True, message="l1_disabled_skip", stats={})
    if not l1_cfg.maintenance_enabled:
        return ScheduledExecutionResult(success=True, message="l1_maintenance_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L1 maintenance skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    async with unified.memory_operation_guard():
        if unified.l1 is None:
            return ScheduledExecutionResult(
                success=True,
                message="l1_uninitialized_skip",
                stats={},
            )

        try:
            stats = await unified.cleanup_l1_data(
                older_than_days=int(l1_cfg.retention_days),
                history_behavior=getattr(
                    memory_cfg.history_behavior,
                    "value",
                    str(memory_cfg.history_behavior),
                ),
            )
        except Exception as exc:
            logger.error("L1 maintenance failed", error=str(exc))
            return ScheduledExecutionResult(
                success=False,
                message="l1_maintenance_failed",
                stats={"error": str(exc)},
            )

        return ScheduledExecutionResult(
            success=True,
            message="l1_maintenance_ok",
            stats=stats,
        )


class L1MaintenanceScheduleContrib:
    """Registers MEMORY_L1_MAINTENANCE handler and interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(
            ScheduledTargetType.MEMORY_L1_MAINTENANCE,
            handle_l1_maintenance,
        )
        l1_cfg = get_config().agent.memory.l1
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L1_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L1_MAINTENANCE,
            target_key=TARGET_KEY_L1_MAINTENANCE,
            seconds=float(l1_cfg.maintenance_interval_seconds),
            target_payload={},
        )
        logger.info(
            "L1 maintenance schedule registered",
            interval_seconds=l1_cfg.maintenance_interval_seconds,
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L1_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L1_MAINTENANCE,
            target_key=TARGET_KEY_L1_MAINTENANCE,
        )
