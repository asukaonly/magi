"""Scheduler integration for daily mood aggregate computation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from ...core.logger import get_logger
from ...memory.l3.daily_mood.store import DailyMoodAggregateStore
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .algorithm import compute_daily_mood_aggregate
from .sample_source import ValenceSample

logger = get_logger("magi.timeline.mood.scheduler")

SCHEDULE_ID_TIMELINE_MOOD_AGGREGATE = "timeline_mood_aggregate"
TARGET_KEY_TIMELINE_MOOD_AGGREGATE = "timeline_mood_aggregate"
INTERVAL_SECONDS_TIMELINE_MOOD_AGGREGATE = 60 * 60  # 1 hour


class _SampleSourceProtocol(Protocol):
    """Anything that can yield attributable mood samples for a window."""

    async def list_valence_samples(
        self,
        *,
        start: float,
        end: float,
    ) -> list[ValenceSample]: ...


class MoodAggregateSchedulerContrib:
    """End-of-day handler that computes yesterday's mood aggregate."""

    def __init__(
        self,
        *,
        sample_source: _SampleSourceProtocol,
        mood_store: DailyMoodAggregateStore,
    ) -> None:
        self._sample_source = sample_source
        self._mood_store = mood_store

    async def register_schedules(self, scheduler) -> None:
        scheduler.register_handler(
            ScheduledTargetType.TIMELINE_MOOD_AGGREGATE,
            self._handle_aggregate,
        )
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_TIMELINE_MOOD_AGGREGATE,
            target_type=ScheduledTargetType.TIMELINE_MOOD_AGGREGATE,
            target_key=TARGET_KEY_TIMELINE_MOOD_AGGREGATE,
            seconds=float(INTERVAL_SECONDS_TIMELINE_MOOD_AGGREGATE),
            target_payload={},
        )

    async def unregister_schedules(self, scheduler) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_TIMELINE_MOOD_AGGREGATE,
            target_type=ScheduledTargetType.TIMELINE_MOOD_AGGREGATE,
            target_key=TARGET_KEY_TIMELINE_MOOD_AGGREGATE,
        )

    async def _handle_aggregate(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        triggered_at = float(getattr(context, "triggered_at", 0.0) or 0.0)
        if triggered_at <= 0:
            triggered_at = datetime.now(tz=timezone.utc).timestamp()

        triggered_dt = datetime.fromtimestamp(triggered_at, tz=timezone.utc)
        yesterday = triggered_dt.date() - timedelta(days=1)
        period_start_dt = datetime(
            yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc
        )
        period_end_dt = period_start_dt + timedelta(days=1)

        period_start = period_start_dt.timestamp()
        period_end = period_end_dt.timestamp()

        try:
            samples = await self._sample_source.list_valence_samples(
                start=period_start,
                end=period_end,
            )
        except Exception as exc:
            logger.warning("Mood sample fetch failed", error=str(exc), date=yesterday.isoformat())
            return ScheduledExecutionResult(
                success=False,
                message=f"sample fetch failed: {exc}",
                stats={},
            )

        # Shift sample timestamps to be relative to day start so the
        # algorithm's hourly bucketing maps correctly.
        relative_samples: list[tuple[float, float]] = []
        source_event_ids: list[str] = []
        for sample in samples:
            relative_samples.append((sample.timestamp - period_start, sample.valence))
            source_event_ids.extend(sample.source_event_ids)

        agg = compute_daily_mood_aggregate(
            day_local_date=yesterday.isoformat(),
            samples=relative_samples,
            source_event_ids=source_event_ids,
        )
        stored = await self._mood_store.upsert_aggregate(agg)
        if stored is False:
            return ScheduledExecutionResult(
                success=True,
                message=f"mood aggregate skipped for forgotten sources on {yesterday.isoformat()}",
                stats={"skipped_forgotten_sources": True},
            )

        return ScheduledExecutionResult(
            success=True,
            message=f"mood aggregate computed for {yesterday.isoformat()}",
            stats={
                "event_count": agg.event_count,
                "dominant_valence": agg.dominant_valence,
                "volatility_score": agg.volatility_score,
            },
        )
