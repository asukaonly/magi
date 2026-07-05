"""Tests for the independent L2 episode/experience consolidation schedule."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.config.memory_models import MemoryL2Settings
from magi.scheduler.contracts import ScheduledTargetType


def _make_dummy_context() -> Any:
    return MagicMock()


def _build_config(
    *,
    l2_enabled: bool = True,
    consolidation_enabled: bool = True,
) -> Any:
    l2_cfg = MemoryL2Settings(
        enabled=l2_enabled,
        consolidation_enabled=consolidation_enabled,
    )
    memory_cfg = SimpleNamespace(l2=l2_cfg)
    return SimpleNamespace(agent=SimpleNamespace(memory=memory_cfg))


def test_scheduled_target_type_includes_memory_l2_consolidate():
    """MEMORY_L2_CONSOLIDATE must be a valid ScheduledTargetType member."""
    assert ScheduledTargetType.MEMORY_L2_CONSOLIDATE == "memory_l2_consolidate"
    assert (
        ScheduledTargetType("memory_l2_consolidate")
        is ScheduledTargetType.MEMORY_L2_CONSOLIDATE
    )


@pytest.mark.asyncio
async def test_l2_consolidation_contrib_registers_handler_and_schedule():
    """The consolidation contrib wires the handler and configured interval."""
    from magi.memory.l2.consolidation_schedule import (
        L2ConsolidationScheduleContrib,
        SCHEDULE_ID_L2_CONSOLIDATE,
        TARGET_KEY_L2_CONSOLIDATE,
        handle_l2_consolidation,
    )

    registered_handlers: dict[ScheduledTargetType, Any] = {}
    scheduled_intervals: list[dict[str, Any]] = []

    class FakeScheduler:
        def register_handler(self, target_type, handler):
            registered_handlers[target_type] = handler

        async def schedule_interval(self, *, schedule_id, target_type, target_key, seconds, target_payload):
            scheduled_intervals.append({
                "schedule_id": schedule_id,
                "target_type": target_type,
                "target_key": target_key,
                "seconds": seconds,
            })

        async def unschedule(self, schedule_id, *, target_type, target_key):
            pass

    l2_cfg = MemoryL2Settings(consolidation_interval_seconds=43_200.0)
    cfg_mock = SimpleNamespace(agent=SimpleNamespace(memory=SimpleNamespace(l2=l2_cfg)))

    contrib = L2ConsolidationScheduleContrib()
    with patch("magi.memory.l2.consolidation_schedule.get_config", return_value=cfg_mock):
        await contrib.register_schedules(FakeScheduler())

    assert registered_handlers[ScheduledTargetType.MEMORY_L2_CONSOLIDATE] is handle_l2_consolidation
    assert len(scheduled_intervals) == 1
    si = scheduled_intervals[0]
    assert si["schedule_id"] == SCHEDULE_ID_L2_CONSOLIDATE
    assert si["target_type"] == ScheduledTargetType.MEMORY_L2_CONSOLIDATE
    assert si["target_key"] == TARGET_KEY_L2_CONSOLIDATE
    assert si["seconds"] == 43_200.0


@pytest.mark.asyncio
async def test_consolidation_handler_promotes_episodes_experiences_and_summaries():
    """The consolidation handler owns episode promotion, experience promotion, and summaries."""
    from magi.memory.l2.episode_formation import EpisodeConsolidationStats
    from magi.memory.l2.experiences.models import ExperiencePromotionStats
    from magi.memory.l2.consolidation_schedule import handle_l2_consolidation

    l2_store = MagicMock()
    l2_store.get_experience = AsyncMock(return_value={
        "experience_id": "exp-a",
        "title": "Launch week",
        "time_start": 1,
        "time_end": 2,
    })
    l2_store.list_experience_members = AsyncMock(return_value=[
        {"member_type": "episode", "member_id": "ep-a", "role": "core", "confidence": 0.8}
    ])
    l2_store.update_experience = AsyncMock(return_value=True)
    l1_store = MagicMock()
    l3_store = MagicMock()
    l3_store.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 2, "errors": ["ep-b: timeout"]}
    )
    l3_store.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    l3_store.generate_experience_summary = AsyncMock(return_value={
        "summary_id": "sum-exp-a",
        "content": "Experience recap",
    })

    pipeline_mock = MagicMock()
    pipeline_mock._cognition_store = l2_store

    unified_mock = MagicMock()
    unified_mock.l2 = l2_store
    unified_mock.l2_pipeline = pipeline_mock
    unified_mock.l1 = l1_store
    unified_mock.l3 = l3_store
    unified_mock.scenario_llm_pool = object()

    consolidation_stats = EpisodeConsolidationStats(promoted=2)
    consolidation_stats.promoted_episode_ids = ["ep-a", "ep-b"]
    consolidate_mock = AsyncMock(return_value=consolidation_stats)
    promote_mock = AsyncMock(return_value=ExperiencePromotionStats(
        candidates=1,
        promoted=1,
        promoted_experience_ids=["exp-a"],
    ))

    with (
        patch("magi.memory.l2.consolidation_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.consolidation_schedule.get_config", return_value=_build_config()),
        patch("magi.memory.l2.episode_formation.consolidate_episodes", new=consolidate_mock),
        patch("magi.memory.l2.experiences.promotion.promote_experiences_from_episodes", new=promote_mock),
    ):
        result = await handle_l2_consolidation(_make_dummy_context())

    assert result.success is True
    assert result.message == "consolidation_ok"
    consolidate_mock.assert_awaited_once_with(l2_store)
    promote_mock.assert_awaited_once()
    promote_kwargs = promote_mock.await_args.kwargs
    assert promote_mock.await_args.args == (l2_store,)
    assert callable(promote_kwargs["selector"])
    l3_store.generate_missing_episodic_summaries.assert_awaited_once()
    call_kwargs = l3_store.generate_missing_episodic_summaries.await_args.kwargs
    assert call_kwargs["l1_store"] is l1_store
    assert call_kwargs["l2_store"] is l2_store
    assert call_kwargs["episode_ids"] == ["ep-a", "ep-b"]
    l3_store.generate_experience_summary.assert_awaited_once()
    assert result.stats["episodes_promoted"] == 2
    assert result.stats["episodic_summaries_generated"] == 2
    assert result.stats["experience_candidates"] == 1
    assert result.stats["experiences_promoted"] == 1
    assert result.stats["experience_summaries_generated"] == 1


@pytest.mark.asyncio
async def test_consolidation_handler_respects_config_gate():
    """consolidation_enabled=False skips the task without touching L2."""
    from magi.memory.l2.consolidation_schedule import handle_l2_consolidation

    with patch("magi.memory.l2.consolidation_schedule.get_config", return_value=_build_config(consolidation_enabled=False)):
        result = await handle_l2_consolidation(_make_dummy_context())

    assert result.success is True
    assert result.message == "l2_consolidation_disabled_skip"
