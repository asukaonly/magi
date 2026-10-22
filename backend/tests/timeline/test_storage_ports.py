"""Timeline reads operate with repositories that expose no database paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.l3.daily_mood.models import DailyMoodAggregate
from magi.timeline.service import TimelineService


@pytest.mark.asyncio
async def test_pathless_memory_repositories_serve_mood_and_visible_assets():
    memory = SimpleNamespace(
        daily_mood=SimpleNamespace(
            list_aggregates=AsyncMock(return_value=[DailyMoodAggregate("2026-01-04")])
        ),
        asset_references=SimpleNamespace(is_visible_reference=AsyncMock(return_value=True)),
    )
    covers = SimpleNamespace(
        references_asset=AsyncMock(
            side_effect=AssertionError("Memory owner already granted visibility")
        )
    )
    assets = SimpleNamespace(resolve=lambda _: (b"image", "image/png"))
    service = TimelineService(memory, cover_repository=covers, manual_entry_asset_store=assets)
    mood = await service.list_mood_calendar(month="2026-01")
    assert mood["days"][0]["date"] == "2026-01-04"
    memory.daily_mood.list_aggregates.assert_awaited_once_with(
        start_date="2026-01-01", end_date="2026-01-31"
    )
    assert await service.serve_asset(asset_ref="manual-entry-asset://image") == (
        b"image",
        "image/png",
    )
    covers.references_asset.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeline_cover_owner_is_consulted_separately_from_memory():
    memory = SimpleNamespace(
        asset_references=SimpleNamespace(is_visible_reference=AsyncMock(return_value=False))
    )
    covers = SimpleNamespace(references_asset=AsyncMock(return_value=True))
    service = TimelineService(
        memory,
        cover_repository=covers,
        manual_entry_asset_store=SimpleNamespace(resolve=lambda _: (b"image", "image/png")),
    )
    assert await service.serve_asset(asset_ref="manual-entry-asset://cover") == (
        b"image",
        "image/png",
    )
    covers.references_asset.return_value = False
    assert await service.serve_asset(asset_ref="manual-entry-asset://cover") is None
