"""Scheduler integration for diary narrative generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from ...core.logger import get_logger
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)

logger = get_logger("magi.timeline.narrative.scheduler")

SCHEDULE_ID_TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
TARGET_KEY_TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
INTERVAL_SECONDS_TIMELINE_DIARY_NARRATIVE = 6 * 60 * 60  # 6 hours


class _OrchestratorProtocol(Protocol):
    async def generate_for_window(
        self, *, scale: str, period_start: float, period_end: float, insight_key: str,
        place_hints=...,
    ) -> object: ...


class _SchedulerProtocol(Protocol):
    async def register_handler(self, target_type, handler) -> None: ...


class DiaryNarrativeSchedulerContrib:
    """Register an end-of-day diary narrative job.

    The handler computes "yesterday's day window" relative to the trigger time
    (UTC for now; localization is a Plan 3 concern), then dispatches to the
    orchestrator with insight_key = "diary-day-YYYY-MM-DD".

    Week/month variants can be added by extending this contributor with
    additional target_type registrations — kept day-only for Plan 2 scope.
    """

    def __init__(self, *, orchestrator: _OrchestratorProtocol) -> None:
        self._orchestrator = orchestrator

    async def register_schedules(self, scheduler: _SchedulerProtocol) -> None:
        scheduler.register_handler(
            ScheduledTargetType.TIMELINE_DIARY_NARRATIVE,
            self._handle_diary_narrative,
        )
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_TIMELINE_DIARY_NARRATIVE,
            target_type=ScheduledTargetType.TIMELINE_DIARY_NARRATIVE,
            target_key=TARGET_KEY_TIMELINE_DIARY_NARRATIVE,
            seconds=float(INTERVAL_SECONDS_TIMELINE_DIARY_NARRATIVE),
            target_payload={},
        )

    async def unregister_schedules(self, scheduler) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_TIMELINE_DIARY_NARRATIVE,
            target_type=ScheduledTargetType.TIMELINE_DIARY_NARRATIVE,
            target_key=TARGET_KEY_TIMELINE_DIARY_NARRATIVE,
        )

    async def _handle_diary_narrative(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        triggered_at = float(getattr(context, "triggered_at", 0.0) or 0.0)
        if triggered_at <= 0:
            triggered_at = datetime.now(tz=timezone.utc).timestamp()

        triggered_dt = datetime.fromtimestamp(triggered_at, tz=timezone.utc)
        yesterday = triggered_dt.date() - timedelta(days=1)
        period_start_dt = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
        period_end_dt = period_start_dt + timedelta(days=1)

        period_start = period_start_dt.timestamp()
        period_end = period_end_dt.timestamp()
        insight_key = f"diary-day-{yesterday.isoformat()}"

        try:
            result = await self._orchestrator.generate_for_window(
                scale="day",
                period_start=period_start,
                period_end=period_end,
                insight_key=insight_key,
                place_hints=[],
            )
        except Exception as exc:
            logger.warning("Diary narrative generation failed", error=str(exc), insight_key=insight_key)
            return ScheduledExecutionResult(
                success=False, message=f"diary narrative failed: {exc}", stats={},
            )

        stats = {
            "episode_count": getattr(result, "episode_count", 0),
            "essence_prose_chars": getattr(result, "essence_prose_chars", 0),
            "slices_written": getattr(result, "slices_written", 0),
        }
        return ScheduledExecutionResult(
            success=True,
            message=f"diary narrative generated for {yesterday.isoformat()}",
            stats=stats,
        )
