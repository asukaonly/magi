from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from magi.user_profile.portrait_projection_scheduler import (
    UserPortraitProjectionScheduler,
    get_portrait_projection_scheduler,
    register_l2_portrait_projection_refresh,
    schedule_portrait_projection_refresh,
)
from magi.user_profile.portrait_projection_repository import (
    UserPortraitProjectionRepository,
)
from magi.user_profile.projection_freshness import profile_projection_highwater
from magi.user_profile.projection_repository import UserProfileProjectionRepository


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
async def test_runtime_refresh_rebuilds_profile_before_portrait(tmp_path):
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.core.sqlite import sqlite_connection_async
    from magi.memory.l2.corrections.repository import MemoryCorrectionRepository

    await apply_memory_shared_schema(str(tmp_path / "memory.db"))

    class _L2:
        db_path = str(tmp_path / "memory.db")

        def __init__(self):
            self.handlers = {}
            self.assertion_callback = None
            self.name = "明日香"
            self.revision = 0

        def register_memory_correction_job_handler(self, kind, handler):
            self.handlers[kind] = handler

        def set_assertion_change_callback(self, callback):
            self.assertion_callback = callback

        async def list_current_assertions(self, **_kwargs):
            return [
                {
                    "assertion_id": "assert-name",
                    "trait_family": "identity_profile",
                    "trait_name": "identity.real_name",
                    "trait_value": self.name,
                    "validation_state": "stable",
                    "source_domain": "user_authored",
                    "updated_at": 10.0 + self.revision,
                }
            ]

        async def current_subject_revision(self, _entity_id: str) -> int:
            return self.revision

        async def current_clear_generation(self) -> int:
            return 0

    memory = SimpleNamespace(
        l2=_L2(),
        _memory_config_getter=lambda: SimpleNamespace(
            l2=SimpleNamespace(portrait_projection_refresh_delay_seconds=0.0)
        ),
    )
    register_l2_portrait_projection_refresh(memory)
    assert set(memory.l2.handlers) == {"profile", "portrait"}
    scheduler = get_portrait_projection_scheduler(memory)
    assert scheduler is not None

    await schedule_portrait_projection_refresh(memory, "local_user")
    await scheduler.wait_idle()

    profile = await UserProfileProjectionRepository(memory.l2.db_path).get("local_user")
    portrait = await UserPortraitProjectionRepository(memory.l2.db_path).get("local_user")
    assert profile is not None
    assert portrait is not None
    assert profile.real_name == "明日香"
    assert portrait.input_profile_highwater == profile_projection_highwater(profile)
    assert "明日香" in str(portrait.world)

    memory.l2.name = "未来"
    repository = MemoryCorrectionRepository(memory.l2.db_path)
    async with sqlite_connection_async(memory.l2.db_path) as db:
        memory.l2.revision = await repository.bump_subject_revision(db, subject_key="user:local_user")
        await db.commit()
    await memory.l2.assertion_callback(_assertion(entity_id="user:local_user"))
    await scheduler.wait_idle()
    refreshed = await UserProfileProjectionRepository(memory.l2.db_path).get("local_user")
    assert refreshed.real_name == "未来"
    portrait = await UserPortraitProjectionRepository(memory.l2.db_path).get("local_user")
    assert "未来" in str(portrait.world) and "明日香" not in str(portrait.world)
    memory.l2.name = "更正姓名"
    async with sqlite_connection_async(memory.l2.db_path) as db:
        memory.l2.revision = await repository.bump_subject_revision(db, subject_key="user:local_user")
        await db.commit()
    job = {"target_key": "user:local_user", "target_revision": 2}
    await memory.l2.handlers["profile"](job)
    corrected = await UserProfileProjectionRepository(memory.l2.db_path).get("local_user")
    assert corrected.real_name == "更正姓名"
    await memory.l2.handlers["portrait"](job)
    portrait = await UserPortraitProjectionRepository(memory.l2.db_path).get("local_user")
    assert "更正姓名" in str(portrait.world) and "未来" not in str(portrait.world)
    assert portrait.input_profile_highwater == profile_projection_highwater(corrected)
    await scheduler.shutdown()


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
