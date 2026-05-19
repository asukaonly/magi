"""Tests for RepresentativeAssetPopulateSchedulerContrib."""

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
    from magi.media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib

    contrib = RepresentativeAssetPopulateSchedulerContrib(
        l2_store=AsyncMock(), selector=AsyncMock(),
    )
    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()         # SYNC now
    scheduler.schedule_interval = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_called_once()
    handler_args = scheduler.register_handler.call_args.args
    assert handler_args[0] == ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET

    scheduler.schedule_interval.assert_awaited_once()
    interval_kwargs = scheduler.schedule_interval.call_args.kwargs
    assert interval_kwargs["target_type"] == ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET
    assert interval_kwargs["seconds"] > 0


@pytest.mark.asyncio
async def test_handler_populates_missing_refs(l2_store_with_schema):
    from magi.media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    # Seed: 2 episodes, neither has a representative_asset_ref yet
    await l2_store_with_schema.create_episode(
        episode_id="ep-a", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-a", status="active")
    await l2_store_with_schema.create_episode(
        episode_id="ep-b", time_start=300.0, time_end=400.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-b", status="active")

    # Stub source that returns a photo only for episode A's window
    class _StubSource:
        source_id = "photo-library"

        async def list_assets(self, *, start: float, end: float) -> list[dict]:
            if start <= 150.0 <= end:
                return [{"ref": "photo-library://A.HEIC", "timestamp": 150.0}]
            return []

    registry = MediaSourceRegistry()
    registry.register(_StubSource())
    selector = MediaSelector(registry=registry)

    contrib = RepresentativeAssetPopulateSchedulerContrib(
        l2_store=l2_store_with_schema, selector=selector,
    )

    result = await contrib._handle_populate(_make_context(1000.0))
    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True

    ep_a = await l2_store_with_schema.get_episode(episode_id="ep-a")
    ep_b = await l2_store_with_schema.get_episode(episode_id="ep-b")

    assert ep_a["representative_asset_ref"] == "photo-library://A.HEIC"
    # Episode B's window had no photos → stays empty
    assert ep_b["representative_asset_ref"] == ""


@pytest.mark.asyncio
async def test_handler_does_not_overwrite_existing_ref(l2_store_with_schema):
    from magi.media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    await l2_store_with_schema.create_episode(
        episode_id="ep-pre", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(
        episode_id="ep-pre", status="active",
        representative_asset_ref="photo-library://existing.HEIC",
    )

    # Selector would return a different ref if asked
    class _StubSource:
        source_id = "photo-library"
        async def list_assets(self, *, start, end):
            return [{"ref": "photo-library://newer.HEIC", "timestamp": 150.0}]

    registry = MediaSourceRegistry()
    registry.register(_StubSource())
    selector = MediaSelector(registry=registry)

    contrib = RepresentativeAssetPopulateSchedulerContrib(
        l2_store=l2_store_with_schema, selector=selector,
    )

    await contrib._handle_populate(_make_context(1000.0))
    ep = await l2_store_with_schema.get_episode(episode_id="ep-pre")
    assert ep["representative_asset_ref"] == "photo-library://existing.HEIC"
