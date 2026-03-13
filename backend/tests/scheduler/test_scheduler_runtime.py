from __future__ import annotations

import asyncio

import pytest

from magi.scheduler.runtime import request_scheduler_refresh, set_scheduler_runtime


class _FakeBootstrap:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def sync_timeline_sensor_schedules(self) -> None:
        self.calls += 1
        self.started.set()
        await self.release.wait()


@pytest.mark.asyncio
async def test_request_scheduler_refresh_serializes_and_replays_pending_work():
    bootstrap = _FakeBootstrap()
    set_scheduler_runtime(object(), bootstrap)  # type: ignore[arg-type]

    try:
        request_scheduler_refresh()
        await asyncio.wait_for(bootstrap.started.wait(), timeout=1.0)

        request_scheduler_refresh()
        bootstrap.release.set()
        await asyncio.sleep(0.05)

        assert bootstrap.calls == 2
    finally:
        set_scheduler_runtime(None, None)
