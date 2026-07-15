"""Scheduler integration for periodic L3 temporal summary cascade."""

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

SCHEDULE_ID_L3_HOUR = "memory-l3-summary:hour"
SCHEDULE_ID_L3_DAY = "memory-l3-summary:day"
SCHEDULE_ID_L3_WEEK = "memory-l3-summary:week"
SCHEDULE_ID_L3_MONTH = "memory-l3-summary:month"
TARGET_KEY_L3_SUMMARY = "memory_l3_summary"
SCHEDULE_ID_L3_ACTIVITY_PREFIX = "memory-l3-activity:"

_CORE_PERIOD_SCHEDULES: tuple[tuple[str, str], ...] = (
    ("hour", SCHEDULE_ID_L3_HOUR),
    ("day", SCHEDULE_ID_L3_DAY),
    ("week", SCHEDULE_ID_L3_WEEK),
    ("month", SCHEDULE_ID_L3_MONTH),
)

_PERIOD_INTERVALS: dict[str, float] = {
    "hour": 3600.0,
    "day": 86400.0,
    "week": 604800.0,
    "month": 2592000.0,
}


async def handle_l3_summary(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Generate a temporal L3 summary for the period specified in payload."""
    payload = context.schedule.target_payload or {}
    period_type = str(payload.get("period_type", "hour"))
    summary_category = payload.get("summary_category") or None
    source_filter = payload.get("source_filter") or None
    min_events = int(payload.get("min_events") or 1)

    memory_cfg = get_config().agent.memory
    if not memory_cfg.l3.enabled:
        return ScheduledExecutionResult(success=True, message="l3_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L3 summary skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    async with unified.memory_operation_guard():
        if unified.l3 is None or unified.l1 is None:
            return ScheduledExecutionResult(
                success=True,
                message="l3_or_l1_uninitialized_skip",
                stats={},
            )

        try:
            summary = await unified.generate_summary(
                period_type=period_type,
                summary_category=summary_category,
                source_filter=list(source_filter) if source_filter else None,
                min_events=min_events,
            )
        except Exception as exc:
            logger.error("L3 %s summary generation failed", period_type, error=str(exc))
            return ScheduledExecutionResult(
                success=False,
                message="generation_failed",
                stats={
                    "period_type": period_type,
                    "summary_category": summary_category,
                    "source_filter": source_filter,
                    "error": str(exc),
                },
            )

        generated = summary is not None
        return ScheduledExecutionResult(
            success=True,
            message="generated" if generated else "no_events",
            stats={
                "period_type": period_type,
                "summary_category": summary_category,
                "source_filter": source_filter,
                "generated": generated,
            },
        )


def _activity_schedule_id(summary_category: str, window: str) -> str:
    return f"{SCHEDULE_ID_L3_ACTIVITY_PREFIX}{summary_category}:{window}"


class L3SummaryScheduleContrib:
    """Registers MEMORY_L3_SUMMARY handler and interval schedules for core periods."""

    def __init__(self) -> None:
        self._activity_schedule_ids: list[str] = []

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L3_SUMMARY, handle_l3_summary)

        # Schedules are always written so toggling l3.enabled at runtime takes effect
        # without a restart. The handler short-circuits with l3_disabled_skip when the
        # layer is off, so disabled runs are cheap no-ops.
        for period_type, schedule_id in _CORE_PERIOD_SCHEDULES:
            await scheduler.schedule_interval(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                target_key=TARGET_KEY_L3_SUMMARY,
                seconds=_PERIOD_INTERVALS[period_type],
                target_payload={"period_type": period_type},
            )
        logger.info("L3 summary schedules registered (hour/day/week/month)")

        await self._register_activity_schedules(scheduler)

    async def _register_activity_schedules(self, scheduler: SchedulerService) -> None:
        try:
            from ...plugins.provider import resolve_plugin_projection_service

            plugin_projection_service = resolve_plugin_projection_service()
        except (RuntimeError, ImportError):
            logger.debug(
                "Plugin projection service unavailable; skipping activity summary schedules"
            )
            return

        try:
            merged_profiles = plugin_projection_service.iter_merged_summary_profiles()
        except Exception as exc:
            logger.warning("iter_merged_summary_profiles failed: %s", exc)
            return

        new_ids: list[str] = []
        for profile in merged_profiles:
            if not profile.source_types:
                continue
            for window in profile.windows:
                if window not in _PERIOD_INTERVALS:
                    continue
                schedule_id = _activity_schedule_id(profile.summary_category, window)
                await scheduler.schedule_interval(
                    schedule_id=schedule_id,
                    target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                    target_key=TARGET_KEY_L3_SUMMARY,
                    seconds=_PERIOD_INTERVALS[window],
                    target_payload={
                        "period_type": window,
                        "summary_category": profile.summary_category,
                        "source_filter": list(profile.source_types),
                        "min_events": int(profile.min_events),
                        "contributing_profile_ids": list(profile.contributing_profile_ids),
                    },
                )
                new_ids.append(schedule_id)

        # Drop any previously-registered category schedules no longer present.
        for stale_id in self._activity_schedule_ids:
            if stale_id not in new_ids:
                await scheduler.unschedule(
                    stale_id,
                    target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                    target_key=TARGET_KEY_L3_SUMMARY,
                )
        self._activity_schedule_ids = new_ids
        if new_ids:
            logger.info(
                "L3 activity summary schedules registered",
                extra={"count": len(new_ids), "schedule_ids": new_ids},
            )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        for _period_type, sid in _CORE_PERIOD_SCHEDULES:
            await scheduler.unschedule(
                sid,
                target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                target_key=TARGET_KEY_L3_SUMMARY,
            )
        for sid in self._activity_schedule_ids:
            await scheduler.unschedule(
                sid,
                target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
                target_key=TARGET_KEY_L3_SUMMARY,
            )
        self._activity_schedule_ids.clear()
