"""Scheduler integration for periodic L3 summary-retention maintenance."""

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


SCHEDULE_ID_L3_MAINTENANCE = "memory-l3-maintenance:global"
TARGET_KEY_L3_MAINTENANCE = "memory_l3_maintenance"


async def handle_l3_maintenance(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Run L3 summary-retention cleanup independently from global runtime maintenance."""
    _ = context
    memory_cfg = get_config().agent.memory
    l3_cfg = memory_cfg.l3
    if not l3_cfg.enabled:
        return ScheduledExecutionResult(success=True, message="l3_disabled_skip", stats={})
    if not l3_cfg.maintenance_enabled:
        return ScheduledExecutionResult(success=True, message="l3_maintenance_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L3 maintenance skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    async with unified.memory_operation_guard():
        if unified.l3 is None:
            return ScheduledExecutionResult(
                success=True,
                message="l3_uninitialized_skip",
                stats={},
            )

        try:
            stats = await unified.cleanup_l3_data(
                older_than_days=int(l3_cfg.retention_days),
                history_behavior=getattr(
                    memory_cfg.history_behavior,
                    "value",
                    str(memory_cfg.history_behavior),
                ),
            )
        except Exception as exc:
            logger.error("L3 maintenance failed", error=str(exc))
            return ScheduledExecutionResult(
                success=False,
                message="l3_maintenance_failed",
                stats={"error": str(exc)},
            )

        return ScheduledExecutionResult(
            success=True,
            message="l3_maintenance_ok",
            stats=stats,
        )


class L3MaintenanceScheduleContrib:
    """Registers MEMORY_L3_MAINTENANCE handler and interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(
            ScheduledTargetType.MEMORY_L3_MAINTENANCE,
            handle_l3_maintenance,
        )
        l3_cfg = get_config().agent.memory.l3
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L3_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L3_MAINTENANCE,
            target_key=TARGET_KEY_L3_MAINTENANCE,
            seconds=float(l3_cfg.maintenance_interval_seconds),
            target_payload={},
        )
        logger.info(
            "L3 maintenance schedule registered",
            interval_seconds=l3_cfg.maintenance_interval_seconds,
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L3_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L3_MAINTENANCE,
            target_key=TARGET_KEY_L3_MAINTENANCE,
        )
