from __future__ import annotations

import asyncio
from typing import Any

import pytest

from magi.user_profile.portrait_projection_scheduler import UserPortraitProjectionScheduler


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
