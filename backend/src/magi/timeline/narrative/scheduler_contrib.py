"""Scheduler integration for diary narrative generation."""

from __future__ import annotations

from datetime import datetime, timedelta
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
        """Generate diary narratives for one or more recent days.

        Default: writes yesterday's narrative (the periodic-tick behavior).

        Override via ``target_payload``:
          - ``days`` (int): how many recent days to (re)generate, starting
            from "yesterday" and walking backward. Useful from manual
            triggers to backfill a window in one shot
            (e.g. ``{"days": 7}`` re-writes the past week).

        Per-day failures are isolated — one bad LLM call doesn't abort
        the rest. The aggregate ScheduledExecutionResult lists totals
        plus per-day breakdown.
        """
        triggered_at = float(getattr(context, "triggered_at", 0.0) or 0.0)
        if triggered_at <= 0:
            triggered_at = datetime.now().timestamp()

        payload = getattr(context.schedule, "target_payload", {}) or {}
        try:
            days = max(1, int(payload.get("days") or 1))
        except (TypeError, ValueError):
            days = 1

        # Use local time so "yesterday" and the window boundaries align with
        # what the user sees in the UI (which uses local-time arithmetic).
        triggered_date = datetime.fromtimestamp(triggered_at).date()  # local

        # Walk backward from yesterday — offset 1 = yesterday, 2 = day before, ...
        per_day_results: list[dict] = []
        total_slices_written = 0
        total_episodes = 0
        total_essence_chars = 0
        failures: list[str] = []

        for offset in range(1, days + 1):
            target_date = triggered_date - timedelta(days=offset)
            period_start_dt = datetime(target_date.year, target_date.month, target_date.day)
            period_end_dt = period_start_dt + timedelta(days=1)
            insight_key = f"diary-day-{target_date.isoformat()}"

            try:
                result = await self._orchestrator.generate_for_window(
                    scale="day",
                    period_start=period_start_dt.timestamp(),
                    period_end=period_end_dt.timestamp(),
                    insight_key=insight_key,
                    place_hints=[],
                )
            except Exception as exc:
                logger.warning(
                    "Diary narrative generation failed",
                    error=str(exc), insight_key=insight_key,
                )
                failures.append(target_date.isoformat())
                continue

            per_day_results.append({
                "date": target_date.isoformat(),
                "episode_count": getattr(result, "episode_count", 0),
                "slices_written": getattr(result, "slices_written", 0),
            })
            total_slices_written += getattr(result, "slices_written", 0)
            total_episodes += getattr(result, "episode_count", 0)
            total_essence_chars += getattr(result, "essence_prose_chars", 0)

        if days == 1:
            # Preserve the original single-day message shape so legacy
            # callers / activity feeds read the same way.
            sole_date = (triggered_date - timedelta(days=1)).isoformat()
            return ScheduledExecutionResult(
                success=not failures,
                message=(
                    f"diary narrative generated for {sole_date}"
                    if not failures
                    else f"diary narrative failed for {sole_date}"
                ),
                stats={
                    "episode_count": total_episodes,
                    "essence_prose_chars": total_essence_chars,
                    "slices_written": total_slices_written,
                },
            )

        return ScheduledExecutionResult(
            success=len(per_day_results) > 0,
            message=(
                f"diary backfill: {len(per_day_results)}/{days} days succeeded "
                f"(failures: {','.join(failures) or 'none'})"
            ),
            stats={
                "days_requested": days,
                "days_succeeded": len(per_day_results),
                "days_failed": len(failures),
                "total_episodes": total_episodes,
                "total_slices_written": total_slices_written,
                "total_essence_chars": total_essence_chars,
            },
        )
