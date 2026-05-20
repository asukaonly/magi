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


def _make_context(
    triggered_at: float,
    *,
    target_payload: dict | None = None,
) -> ScheduledExecutionContext:
    """Build a minimally-valid ScheduledExecutionContext for handler tests."""
    schedule = MagicMock(name="schedule")
    # Explicitly set target_payload as a real dict so handler payload
    # reads don't pick up an auto-generated MagicMock attribute.
    schedule.target_payload = target_payload if target_payload is not None else {}
    return ScheduledExecutionContext(
        schedule=schedule,
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
    # New message format includes "diary narrative failed for <date>"; the
    # actual exception is logged but not surfaced in the result to avoid
    # leaking implementation details into the activity feed.
    assert "diary narrative failed" in result.message


@pytest.mark.asyncio
async def test_handler_honors_days_override():
    """``target_payload['days']=N`` triggers N independent generate_for_window
    calls, one per recent day, walking backward from yesterday."""
    from datetime import datetime, timedelta

    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    orchestrator = AsyncMock()
    # Return a result-like object with the stat attributes the handler reads
    result_stub = MagicMock(episode_count=3, slices_written=2, essence_prose_chars=80)
    orchestrator.generate_for_window = AsyncMock(return_value=result_stub)

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)
    triggered_at = 1716292800.0  # 2024-05-21 12:00 UTC
    context = _make_context(triggered_at, target_payload={"days": 3})

    result = await contrib._handle_diary_narrative(context)
    assert result.success is True
    assert orchestrator.generate_for_window.await_count == 3

    # Each call should target a different day, walking backward
    insight_keys_called = [
        call.kwargs["insight_key"]
        for call in orchestrator.generate_for_window.await_args_list
    ]
    triggered_date = datetime.fromtimestamp(triggered_at).date()
    expected = [
        f"diary-day-{(triggered_date - timedelta(days=offset)).isoformat()}"
        for offset in (1, 2, 3)
    ]
    assert insight_keys_called == expected

    # Aggregate stats appear in the result
    assert result.stats["days_requested"] == 3
    assert result.stats["days_succeeded"] == 3
    assert result.stats["total_slices_written"] == 6  # 2 * 3


@pytest.mark.asyncio
async def test_handler_partial_failure_succeeds_when_some_days_work():
    """If one of N days raises, the others still write — aggregate result
    is success=True with days_failed counted in stats."""
    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    orchestrator = AsyncMock()
    # First call succeeds, second raises, third succeeds.
    call_results = [
        MagicMock(episode_count=2, slices_written=2, essence_prose_chars=40),
        RuntimeError("transient LLM error"),
        MagicMock(episode_count=1, slices_written=1, essence_prose_chars=20),
    ]
    orchestrator.generate_for_window = AsyncMock(side_effect=call_results)

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)
    context = _make_context(1716292800.0, target_payload={"days": 3})

    result = await contrib._handle_diary_narrative(context)
    assert result.success is True  # 2/3 succeeded
    assert result.stats["days_succeeded"] == 2
    assert result.stats["days_failed"] == 1


@pytest.mark.asyncio
async def test_handler_invalid_days_falls_back_to_1():
    """Garbage in ``days`` (negative, string, None) collapses to days=1."""
    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    orchestrator = AsyncMock()
    orchestrator.generate_for_window = AsyncMock(return_value=MagicMock(
        episode_count=1, slices_written=1, essence_prose_chars=20,
    ))

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)

    for bad_value in (-3, 0, "seven", None, []):
        orchestrator.generate_for_window.reset_mock()
        context = _make_context(1716292800.0, target_payload={"days": bad_value})
        await contrib._handle_diary_narrative(context)
        assert orchestrator.generate_for_window.await_count == 1, (
            f"days={bad_value!r} should fall back to 1, but got "
            f"{orchestrator.generate_for_window.await_count} calls"
        )
