"""Scheduler integration for periodic L3 temporal summary cascade."""

from __future__ import annotations

from ...config import get_config
from ...core.logger import get_logger
from ...core.runtime_bindings import require_unified_memory
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService

logger = get_logger(__name__)

SCHEDULE_ID_L3_HOUR = "memory-l3-summary:hour"
SCHEDULE_ID_L3_DAY = "memory-l3-summary:day"
SCHEDULE_ID_L3_WEEK = "memory-l3-summary:week"
TARGET_KEY_L3_SUMMARY = "memory_l3_summary"

_PERIOD_INTERVALS: dict[str, float] = {
    "hour": 3600.0,
    "day": 86400.0,
    "week": 604800.0,
}


async def handle_l3_summary(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Generate a temporal L3 summary for the period specified in payload."""
    period_type = context.schedule.target_payload.get("period_type", "hour")

    memory_cfg = get_config().agent.memory
    if not memory_cfg.l3.enabled:
        return ScheduledExecutionResult(success=True, message="l3_disabled_skip", stats={})

    try:
        unified = require_unified_memory()
    except RuntimeError:
        logger.debug("L3 summary skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    if unified.l3 is None or unified.l1 is None:
        return ScheduledExecutionResult(success=True, message="l3_or_l1_uninitialized_skip", stats={})

    try:
        summary = await unified.generate_summary(period_type=period_type)
    except Exception as exc:
        logger.error("L3 %s summary generation failed", period_type, error=str(exc))
        return ScheduledExecutionResult(
            success=False,
            message="generation_failed",
            stats={"period_type": period_type, "error": str(exc)},
        )

    generated = summary is not None
    return ScheduledExecutionResult(
        success=True,
        message="generated" if generated else "no_events",
        stats={"period_type": period_type, "generated": generated},
    )


class L3SummaryScheduleContrib:
    """Registers MEMORY_L3_SUMMARY handler and interval schedules for hour/day/week."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L3_SUMMARY, handle_l3_summary)

        l3_cfg = get_config().agent.memory.l3
        if not l3_cfg.enabled:
            for sid in (SCHEDULE_ID_L3_HOUR, SCHEDULE_ID_L3_DAY, SCHEDULE_ID_L3_WEEK):
                await scheduler.unschedule(
                    sid,
                    target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                    target_key=TARGET_KEY_L3_SUMMARY,
                )
            logger.info("L3 summary schedules disabled by config")
            return

        for period_type, schedule_id in [
            ("hour", SCHEDULE_ID_L3_HOUR),
            ("day", SCHEDULE_ID_L3_DAY),
            ("week", SCHEDULE_ID_L3_WEEK),
        ]:
            await scheduler.schedule_interval(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                target_key=TARGET_KEY_L3_SUMMARY,
                seconds=_PERIOD_INTERVALS[period_type],
                target_payload={"period_type": period_type},
            )
        logger.info("L3 summary schedules registered (hour/day/week)")

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        for sid in (SCHEDULE_ID_L3_HOUR, SCHEDULE_ID_L3_DAY, SCHEDULE_ID_L3_WEEK):
            await scheduler.unschedule(
                sid,
                target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                target_key=TARGET_KEY_L3_SUMMARY,
            )
