"""Tests for MoodAggregateSchedulerContrib."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)


def _make_context(triggered_at: float) -> ScheduledExecutionContext:
    return ScheduledExecutionContext(
        schedule=MagicMock(name="schedule"),
        target_state=MagicMock(name="target_state"),
        runtime_dir=Path("/tmp"),
        triggered_at=triggered_at,
        manual=False,
    )


@pytest.mark.asyncio
async def test_contributor_registers_handler():
    from magi.timeline.mood.scheduler_contrib import MoodAggregateSchedulerContrib

    contrib = MoodAggregateSchedulerContrib(
        sample_source=AsyncMock(),
        mood_store=AsyncMock(),
    )
    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()  # SYNC now
    scheduler.schedule_interval = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_called_once()
    handler_args = scheduler.register_handler.call_args.args
    assert handler_args[0] == ScheduledTargetType.TIMELINE_MOOD_AGGREGATE

    scheduler.schedule_interval.assert_awaited_once()
    interval_kwargs = scheduler.schedule_interval.call_args.kwargs
    assert interval_kwargs["target_type"] == ScheduledTargetType.TIMELINE_MOOD_AGGREGATE
    assert interval_kwargs["seconds"] > 0


@pytest.mark.asyncio
async def test_handler_aggregates_yesterday_and_upserts():
    from magi.timeline.mood.scheduler_contrib import MoodAggregateSchedulerContrib
    from magi.timeline.mood.sample_source import ValenceSample

    # Fake sample source returns 24 hourly samples covering yesterday's window
    # Triggered_at = 2024-05-21 12:00 UTC, yesterday = 2024-05-20 UTC
    # Yesterday's window: [2024-05-20 00:00 UTC, 2024-05-21 00:00 UTC) = [1716163200, 1716249600)
    yesterday_start = 1716163200.0
    sample_source = AsyncMock()
    sample_source.list_valence_samples = AsyncMock(
        return_value=[
            ValenceSample(
                timestamp=yesterday_start + h * 3600,
                valence=0.5,
                source_event_ids=(f"event-{h}",),
            )
            for h in range(24)
        ]
    )

    upserted: list = []
    mood_store = AsyncMock()
    mood_store.upsert_aggregate = AsyncMock(
        side_effect=lambda agg: upserted.append(agg),
    )

    contrib = MoodAggregateSchedulerContrib(
        sample_source=sample_source,
        mood_store=mood_store,
    )
    context = _make_context(1716292800.0)  # 2024-05-21 12:00 UTC

    result = await contrib._handle_aggregate(context)
    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True

    assert len(upserted) == 1
    agg = upserted[0]
    assert agg.day_local_date == "2024-05-20"
    assert agg.dominant_valence == "warm"
    assert agg.volatility_score < 0.1
    assert agg.event_count == 24
    assert agg.source_event_ids == [f"event-{h}" for h in range(24)]


@pytest.mark.asyncio
async def test_handler_returns_failure_when_sample_source_raises():
    from magi.timeline.mood.scheduler_contrib import MoodAggregateSchedulerContrib

    sample_source = AsyncMock()
    sample_source.list_valence_samples = AsyncMock(side_effect=RuntimeError("L2 dead"))
    mood_store = AsyncMock()

    contrib = MoodAggregateSchedulerContrib(
        sample_source=sample_source,
        mood_store=mood_store,
    )
    result = await contrib._handle_aggregate(_make_context(1716292800.0))

    assert result.success is False
    assert "L2 dead" in result.message
    # Mood store should NOT have been called
    mood_store.upsert_aggregate.assert_not_called()
