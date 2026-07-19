import asyncio

import pytest
from magi.outreach.schedule import build_outbox_drain_handler


@pytest.mark.asyncio
async def test_drain_handler_calls_service_and_returns_success():
    drained = []

    class _Svc:
        async def drain_due(self, *, now_ms): drained.append(now_ms)

    class _Producer:
        async def drain_pending(self): return 3

    handler = build_outbox_drain_handler(
        _Svc(),
        _Producer(),
        now_ms=lambda: 4242,
    )
    result = await handler(object())   # scheduler context unused in v1
    assert result.success is True
    assert drained == [4242]
    assert result.stats == {"background_completions": 3}


@pytest.mark.asyncio
async def test_completion_drain_failure_does_not_block_external_outbox():
    drained = []

    class _Svc:
        async def drain_due(self, *, now_ms): drained.append(now_ms)

    class _Producer:
        async def drain_pending(self):
            raise OSError("completion store unavailable")

    handler = build_outbox_drain_handler(
        _Svc(),
        _Producer(),
        now_ms=lambda: 4242,
    )

    result = await handler(object())

    assert result.success is False
    assert drained == [4242]
    assert "background_completion" in result.message


@pytest.mark.asyncio
async def test_drain_handler_serializes_overlapping_runs():
    entered = asyncio.Event()
    release = asyncio.Event()

    class _Svc:
        async def drain_due(self, *, now_ms):
            assert now_ms == 4242

    class _Producer:
        def __init__(self):
            self.calls = 0
            self.active = 0
            self.max_active = 0

        async def drain_pending(self):
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            entered.set()
            await release.wait()
            self.active -= 1
            return 0

    producer = _Producer()
    handler = build_outbox_drain_handler(
        _Svc(),
        producer,
        now_ms=lambda: 4242,
    )
    first = asyncio.create_task(handler(object()))
    await entered.wait()
    second = asyncio.create_task(handler(object()))
    await asyncio.sleep(0)

    assert producer.calls == 1

    release.set()
    await asyncio.gather(first, second)

    assert producer.calls == 2
    assert producer.max_active == 1
