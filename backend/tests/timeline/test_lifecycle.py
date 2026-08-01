"""Tests for TimelineSchedulersModule."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_init_registers_all_contributors_when_deps_present(tmp_path):
    from magi.timeline.lifecycle import TimelineSchedulersModule
    from magi.scheduler.contracts import ScheduledTargetType

    context = MagicMock()
    context.runtime_commands.full_clear_recovery_pending = False
    context.memory.unified_memory.l2 = MagicMock()
    context.memory.unified_memory.l3 = MagicMock()
    context.memory.unified_memory.memory_db_path = str(tmp_path / "memory.db")
    # Location pollers now reuse the sources owned by LocationModule, exposed
    # on context.location (no longer fished off unified_memory).
    context.location.ipgeo_source = MagicMock()
    context.location.wifi_source = MagicMock()
    context.memory.media_source_registry = MagicMock()

    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()
    scheduler.schedule_interval = AsyncMock()
    context.scheduler.scheduler_service = scheduler
    context.llm.scenario_llm_pool = MagicMock()

    module = TimelineSchedulersModule(context)
    await module.init()

    registered_targets = {call.args[0] for call in scheduler.register_handler.call_args_list}
    # Four timeline schedulers...
    assert ScheduledTargetType.TIMELINE_DIARY_NARRATIVE in registered_targets
    assert ScheduledTargetType.TIMELINE_STANDOUT_RESCORE in registered_targets
    assert ScheduledTargetType.TIMELINE_MOOD_AGGREGATE in registered_targets
    assert ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET in registered_targets
    # ...plus two location pollers (IPGeo + WiFi).
    assert ScheduledTargetType.LOCATION_IPGEO_POLL in registered_targets
    assert ScheduledTargetType.LOCATION_WIFI_POLL in registered_targets

    assert scheduler.schedule_interval.await_count == 6


@pytest.mark.asyncio
async def test_init_is_noop_when_scheduler_missing():
    from magi.timeline.lifecycle import TimelineSchedulersModule

    context = MagicMock()
    context.runtime_commands.full_clear_recovery_pending = False
    context.scheduler.scheduler_service = None

    module = TimelineSchedulersModule(context)
    await module.init()  # should not raise


@pytest.mark.asyncio
async def test_shutdown_unregisters_all_contributors(tmp_path):
    from magi.timeline.lifecycle import TimelineSchedulersModule

    context = MagicMock()
    context.runtime_commands.full_clear_recovery_pending = False
    context.memory.unified_memory.l2 = MagicMock()
    context.memory.unified_memory.l3 = MagicMock()
    context.memory.unified_memory.memory_db_path = str(tmp_path / "memory.db")
    # Location pollers now reuse the sources owned by LocationModule, exposed
    # on context.location (no longer fished off unified_memory).
    context.location.ipgeo_source = MagicMock()
    context.location.wifi_source = MagicMock()
    context.memory.media_source_registry = MagicMock()
    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()
    scheduler.schedule_interval = AsyncMock()
    scheduler.unschedule = AsyncMock()
    context.scheduler.scheduler_service = scheduler
    context.llm.scenario_llm_pool = MagicMock()

    module = TimelineSchedulersModule(context)
    await module.init()
    await module.shutdown()

    # 4 timeline + 2 location pollers = 6 unschedule calls
    assert scheduler.unschedule.await_count == 6
