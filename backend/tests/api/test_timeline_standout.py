"""Tests for the standout service method (Plan 1 Task 11)."""

from __future__ import annotations

import pytest

from magi.timeline.service import TimelineService


@pytest.mark.asyncio
async def test_service_list_standout_returns_empty_when_no_episodes(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    out = await service.list_standout(period_start=None, period_end=None, limit=10)
    assert out == []


@pytest.mark.asyncio
async def test_service_list_standout_includes_user_pinned(
    unified_memory_for_tests, l2_store_for_tests,
):
    # 1715990400.0 = 2024-05-18 00:00:00 UTC
    await l2_store_for_tests.create_episode(
        episode_id="ep-x", time_start=1715990400.0, time_end=1715990400.0 + 3600,
    )
    await l2_store_for_tests.update_episode(
        episode_id="ep-x", user_pinned=True, label="跟 Z 在文渊喝咖啡",
    )
    service = TimelineService(unified_memory_for_tests)

    out = await service.list_standout(period_start=None, period_end=None, limit=10)
    assert len(out) == 1
    item = out[0]
    assert item["episode_id"] == "ep-x"
    assert item["source"] == "user"
    assert item["title"] == "跟 Z 在文渊喝咖啡"
    assert item["date"] == "2024-05-18"
