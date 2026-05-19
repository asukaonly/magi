"""Tests for DiaryNarrativeSchedulerContrib."""

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
    """Build a minimally-valid ScheduledExecutionContext for handler tests."""
    return ScheduledExecutionContext(
        schedule=MagicMock(name="schedule"),
        target_state=MagicMock(name="target_state"),
        runtime_dir=Path("/tmp"),
        triggered_at=triggered_at,
        manual=False,
    )


@pytest.mark.asyncio
async def test_scheduler_contrib_registers_handler():
    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=AsyncMock())
    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()         # SYNC now
    scheduler.schedule_interval = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_called_once()
    handler_args = scheduler.register_handler.call_args.args
    assert handler_args[0] == ScheduledTargetType.TIMELINE_DIARY_NARRATIVE

    scheduler.schedule_interval.assert_awaited_once()
    interval_kwargs = scheduler.schedule_interval.call_args.kwargs
    assert interval_kwargs["target_type"] == ScheduledTargetType.TIMELINE_DIARY_NARRATIVE
    assert interval_kwargs["seconds"] > 0


@pytest.mark.asyncio
async def test_handler_calls_orchestrator_for_yesterday_day_window():
    from datetime import datetime, timedelta

    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    orchestrator = AsyncMock()
    orchestrator.generate_for_window = AsyncMock(return_value=None)

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)
    # triggered_at = 2024-05-21 12:00 UTC (1716292800)
    # The scheduler now uses local time, so "yesterday" depends on the host TZ.
    triggered_at = 1716292800.0
    context = _make_context(triggered_at)

    result = await contrib._handle_diary_narrative(context)

    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True

    # Compute the expected values using the same local-time logic as the handler.
    triggered_dt = datetime.fromtimestamp(triggered_at)  # local time
    expected_yesterday = triggered_dt.date() - timedelta(days=1)
    expected_start_dt = datetime(expected_yesterday.year, expected_yesterday.month, expected_yesterday.day)
    expected_end_dt = expected_start_dt + timedelta(days=1)

    orchestrator.generate_for_window.assert_awaited_once()
    call_kwargs = orchestrator.generate_for_window.call_args.kwargs
    assert call_kwargs["scale"] == "day"
    assert call_kwargs["insight_key"] == f"diary-day-{expected_yesterday.isoformat()}"
    assert call_kwargs["period_start"] == pytest.approx(expected_start_dt.timestamp())
    assert call_kwargs["period_end"] == pytest.approx(expected_end_dt.timestamp())


@pytest.mark.asyncio
async def test_handler_returns_failure_when_orchestrator_raises():
    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    orchestrator = AsyncMock()
    orchestrator.generate_for_window = AsyncMock(side_effect=RuntimeError("LLM dead"))

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)
    context = _make_context(1716292800.0)

    result = await contrib._handle_diary_narrative(context)
    assert result.success is False
    assert "LLM dead" in result.message
