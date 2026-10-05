"""Tests for MediaRegistryModule."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_setup_registers_photo_library_source():
    """When MemoryStoreModule has populated unified_memory.l1, the lifecycle
    module instantiates a MediaSourceRegistry and registers the photo adapter."""
    from magi.media.lifecycle import MediaRegistryModule
    from magi.media.source_registry import MediaSourceRegistry

    # Mock the bootstrap context shape
    context = MagicMock()
    l1 = MagicMock()
    l1.query_events = AsyncMock(
        return_value=[
            {
                "event_id": "photo",
                "source": "photo_library",
                "timestamp": 10.0,
                "asset_ref": "p://photo",
            }
        ]
    )
    context.memory.unified_memory.l1 = l1
    context.memory.media_source_registry = None

    module = MediaRegistryModule(context)
    await module.init()

    assert isinstance(context.memory.media_source_registry, MediaSourceRegistry)
    photo_source = context.memory.media_source_registry.get("photo-library")
    assert photo_source is not None
    assert photo_source.source_id == "photo-library"

    assets = await context.memory.media_source_registry.collect_assets(start=0, end=20)
    assert [asset["ref"] for asset in assets] == ["p://photo"]
    l1.query_events.assert_awaited_once()
    await module.shutdown()
    assert context.memory.media_source_registry is None


@pytest.mark.asyncio
async def test_setup_is_noop_when_l1_unavailable():
    """If unified_memory.l1 is None (rare bootstrap ordering issue), the
    module logs and skips registration rather than crashing."""
    from magi.media.lifecycle import MediaRegistryModule

    context = MagicMock()
    context.memory.unified_memory = None
    context.memory.media_source_registry = None

    module = MediaRegistryModule(context)
    await module.init()  # should not raise

    # No registry was created
    assert context.memory.media_source_registry is None
