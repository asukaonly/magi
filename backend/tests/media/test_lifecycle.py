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
    context.memory.unified_memory.l1 = MagicMock(name="l1_store")  # truthy
    context.memory.media_source_registry = None

    module = MediaRegistryModule(context)
    await module.init()

    assert isinstance(context.memory.media_source_registry, MediaSourceRegistry)
    photo_source = context.memory.media_source_registry.get("photo-library")
    assert photo_source is not None
    assert photo_source.source_id == "photo-library"


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


@pytest.mark.asyncio
async def test_teardown_clears_registry():
    from magi.media.lifecycle import MediaRegistryModule
    from magi.media.source_registry import MediaSourceRegistry

    context = MagicMock()
    context.memory.media_source_registry = MediaSourceRegistry()

    module = MediaRegistryModule(context)
    await module.shutdown()

    assert context.memory.media_source_registry is None
