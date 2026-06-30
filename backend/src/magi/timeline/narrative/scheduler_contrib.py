"""Scheduler integration for diary narrative generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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


@dataclass(frozen=True)
class DiaryNarrativeWindow:
    target_date: date
    period_start: float
    period_end: float
    insight_key: str


@dataclass
class DiaryNarrativeRun:
    per_day_results: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    total_slices_written: int = 0
    total_episodes: int = 0
    total_essence_chars: int = 0

    def record_success(self, window: DiaryNarrativeWindow, result: object) -> None:
        self.per_day_results.append(
            {
                "date": window.target_date.isoformat(),
                "episode_count": getattr(result, "episode_count", 0),
                "slices_written": getattr(result, "slices_written", 0),
            }
        )
        self.total_slices_written += getattr(result, "slices_written", 0)
        self.total_episodes += getattr(result, "episode_count", 0)
        self.total_essence_chars += getattr(result, "essence_prose_chars", 0)

    def record_failure(self, window: DiaryNarrativeWindow) -> None:
        self.failures.append(window.target_date.isoformat())


class _OrchestratorProtocol(Protocol):
    async def generate_for_window(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        insight_key: str,
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
        self,
        context: ScheduledExecutionContext,
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
        triggered_date = _triggered_date(context)
        days = _days_to_generate(context)
        run = await self._generate_recent_diary_days(triggered_date, days)
        return _build_execution_result(triggered_date, days, run)

    async def _generate_recent_diary_days(
        self,
        triggered_date: date,
        days: int,
    ) -> DiaryNarrativeRun:
        run = DiaryNarrativeRun()
        for window in _diary_windows(triggered_date, days):
            await self._generate_diary_window(window, run)
        return run

    async def _generate_diary_window(
        self,
        window: DiaryNarrativeWindow,
        run: DiaryNarrativeRun,
    ) -> None:
        try:
            result = await self._orchestrator.generate_for_window(
                scale="day",
                period_start=window.period_start,
                period_end=window.period_end,
                insight_key=window.insight_key,
                place_hints=[],
            )
        except Exception as exc:
            logger.warning(
                "Diary narrative generation failed",
                error=str(exc),
                insight_key=window.insight_key,
            )
            run.record_failure(window)
            return
        run.record_success(window, result)


def _triggered_date(context: ScheduledExecutionContext) -> date:
    triggered_at = float(getattr(context, "triggered_at", 0.0) or 0.0)
    if triggered_at <= 0:
        triggered_at = datetime.now().timestamp()
    return datetime.fromtimestamp(triggered_at).date()


def _days_to_generate(context: ScheduledExecutionContext) -> int:
    payload = getattr(context.schedule, "target_payload", {}) or {}
    try:
        return max(1, int(payload.get("days") or 1))
    except (TypeError, ValueError):
        return 1


def _diary_windows(triggered_date: date, days: int) -> list[DiaryNarrativeWindow]:
    return [_diary_window_for_offset(triggered_date, offset) for offset in range(1, days + 1)]


def _diary_window_for_offset(triggered_date: date, offset: int) -> DiaryNarrativeWindow:
    target_date = triggered_date - timedelta(days=offset)
    period_start_dt = datetime(target_date.year, target_date.month, target_date.day)
    period_end_dt = period_start_dt + timedelta(days=1)
    return DiaryNarrativeWindow(
        target_date=target_date,
        period_start=period_start_dt.timestamp(),
        period_end=period_end_dt.timestamp(),
        insight_key=f"diary-day-{target_date.isoformat()}",
    )


def _build_execution_result(
    triggered_date: date,
    days: int,
    run: DiaryNarrativeRun,
) -> ScheduledExecutionResult:
    if days == 1:
        return _single_day_execution_result(triggered_date, run)
    return _backfill_execution_result(days, run)


def _single_day_execution_result(
    triggered_date: date,
    run: DiaryNarrativeRun,
) -> ScheduledExecutionResult:
    sole_date = (triggered_date - timedelta(days=1)).isoformat()
    return ScheduledExecutionResult(
        success=not run.failures,
        message=(
            f"diary narrative generated for {sole_date}"
            if not run.failures
            else f"diary narrative failed for {sole_date}"
        ),
        stats={
            "episode_count": run.total_episodes,
            "essence_prose_chars": run.total_essence_chars,
            "slices_written": run.total_slices_written,
        },
    )


def _backfill_execution_result(
    days: int,
    run: DiaryNarrativeRun,
) -> ScheduledExecutionResult:
    return ScheduledExecutionResult(
        success=len(run.per_day_results) > 0,
        message=(
            f"diary backfill: {len(run.per_day_results)}/{days} days succeeded "
            f"(failures: {','.join(run.failures) or 'none'})"
        ),
        stats={
            "days_requested": days,
            "days_succeeded": len(run.per_day_results),
            "days_failed": len(run.failures),
            "total_episodes": run.total_episodes,
            "total_slices_written": run.total_slices_written,
            "total_essence_chars": run.total_essence_chars,
        },
    )
