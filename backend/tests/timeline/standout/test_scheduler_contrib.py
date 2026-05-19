"""Tests for StandoutScoringSchedulerContrib."""

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
    from magi.timeline.standout.scheduler_contrib import StandoutScoringSchedulerContrib

    contrib = StandoutScoringSchedulerContrib(
        l2_store=AsyncMock(), media_registry=AsyncMock(),
    )
    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()         # SYNC now
    scheduler.schedule_interval = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_called_once()
    handler_args = scheduler.register_handler.call_args.args
    assert handler_args[0] == ScheduledTargetType.TIMELINE_STANDOUT_RESCORE

    scheduler.schedule_interval.assert_awaited_once()
    interval_kwargs = scheduler.schedule_interval.call_args.kwargs
    assert interval_kwargs["target_type"] == ScheduledTargetType.TIMELINE_STANDOUT_RESCORE
    assert interval_kwargs["seconds"] > 0


@pytest.mark.asyncio
async def test_handler_scores_active_episodes_and_writes_back(
    l2_store_with_schema,
):
    from magi.timeline.standout.scheduler_contrib import StandoutScoringSchedulerContrib
    from magi.media.source_registry import MediaSourceRegistry

    # Seed: one long episode with an entity (alice), one short with no entity
    await l2_store_with_schema.create_episode(
        episode_id="ep-long", time_start=0.0, time_end=7200.0,
        primary_entity_ids=["alice"],
    )
    await l2_store_with_schema.update_episode(episode_id="ep-long", status="active")
    await l2_store_with_schema.create_episode(
        episode_id="ep-short", time_start=8000.0, time_end=8100.0,
        primary_entity_ids=[],
    )
    await l2_store_with_schema.update_episode(episode_id="ep-short", status="active")

    registry = MediaSourceRegistry()  # empty — no photos
    contrib = StandoutScoringSchedulerContrib(
        l2_store=l2_store_with_schema, media_registry=registry,
    )

    result = await contrib._handle_rescore(_make_context(10000.0))
    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True

    long_ep = await l2_store_with_schema.get_episode(episode_id="ep-long")
    short_ep = await l2_store_with_schema.get_episode(episode_id="ep-short")

    # Long episode: 0.35 (duration) + 0.30 (first-entity for "alice") = 0.65, above 0.50 threshold
    assert long_ep["magi_standout"] is True
    assert long_ep["standout_score"] > 0.5
    assert "duration" in long_ep["standout_reason"]
    assert "first_entity" in long_ep["standout_reason"]

    # Short episode — no signals
    assert short_ep["magi_standout"] is False
    assert short_ep["standout_score"] == pytest.approx(0.0)
