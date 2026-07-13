from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from magi.user_profile.portrait_projection_scheduler import (
    UserPortraitProjectionScheduler,
    schedule_portrait_projection_refresh,
)


@pytest.mark.asyncio
async def test_scheduler_debounces_multiple_user_assertion_changes():
    calls: list[str] = []
    sleepers: list[asyncio.Future[None]] = []
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        sleepers.append(future)
        await future

    async def refresh(user_id: str) -> None:
        calls.append(user_id)

    scheduler = UserPortraitProjectionScheduler(
        refresh_callback=refresh,
        delay_seconds=lambda: 12.0,
        sleep=sleep,
    )

    await scheduler.schedule_assertion_change(_assertion(entity_id="user:local_user"))
    await asyncio.sleep(0)
    await scheduler.schedule_assertion_change(_assertion(entity_id="user:local_user"))
    await asyncio.sleep(0)

    for sleeper in sleepers:
        if not sleeper.done():
            sleeper.set_result(None)
    await scheduler.wait_idle()

    assert delays == [12.0, 12.0]
    assert calls == ["local_user"]


@pytest.mark.asyncio
async def test_scheduler_ignores_non_user_assertion_changes():
    calls: list[str] = []

    async def refresh(user_id: str) -> None:
        calls.append(user_id)

    scheduler = UserPortraitProjectionScheduler(
        refresh_callback=refresh,
        delay_seconds=lambda: 0.0,
    )

    await scheduler.schedule_assertion_change(_assertion(entity_id="topic:ai", entity_type="topic"))
    await scheduler.wait_idle()

    assert calls == []


@pytest.mark.asyncio
async def test_schedule_portrait_refresh_targets_known_user(monkeypatch):
    scheduler = AsyncMock()
    memory = object()
    monkeypatch.setattr(
        "magi.user_profile.portrait_projection_scheduler.get_portrait_projection_scheduler",
        lambda unified_memory: scheduler if unified_memory is memory else None,
    )

    await schedule_portrait_projection_refresh(memory, "local_user")

    scheduler.schedule_user.assert_awaited_once_with("local_user")


def _assertion(
    *,
    entity_id: str,
    entity_type: str = "user",
) -> dict[str, Any]:
    return {
        "assertion_id": "assert-1",
        "entity_id": entity_id,
        "entity_type": entity_type,
        "trait_name": "interest.ai",
        "trait_value": "AI",
    }
