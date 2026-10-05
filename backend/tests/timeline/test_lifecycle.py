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
async def test_no_scheduler_prevents_all_contributor_registration(monkeypatch):
    from magi.timeline.lifecycle import TimelineSchedulersModule

    context = MagicMock()
    context.runtime_commands.full_clear_recovery_pending = False
    context.scheduler.scheduler_service = None
    module = TimelineSchedulersModule(context)
    calls = []
    for name in (
        "_register_diary_narrative",
        "_register_standout_rescoring",
        "_register_mood_aggregate",
        "_register_representative_assets",
        "_register_location_pollers",
    ):
        method = AsyncMock(
            side_effect=AssertionError("No schedules can be registered without scheduler")
        )
        calls.append(method)
        monkeypatch.setattr(module, name, method)
    await module.init()
    assert module._contribs == []
    for method in calls:
        method.assert_not_awaited()


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
    registered = {
        call.kwargs["schedule_id"]: (call.kwargs["target_type"], call.kwargs["target_key"])
        for call in scheduler.schedule_interval.await_args_list
    }
    assert set(registered) == {
        "timeline_diary_narrative",
        "timeline_standout_rescore",
        "timeline_mood_aggregate",
        "timeline_representative_asset",
        "location_ipgeo_poll",
        "location_wifi_poll",
    }
    assert scheduler.schedule_interval.await_count == 6
    await module.shutdown()

    assert scheduler.unschedule.await_count == 6
    removed = {
        call.args[0]: (call.kwargs["target_type"], call.kwargs["target_key"])
        for call in scheduler.unschedule.await_args_list
    }
    assert removed == registered
    assert module._contribs == []
