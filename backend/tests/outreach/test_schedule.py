import pytest
from magi.outreach.schedule import build_outbox_drain_handler


@pytest.mark.asyncio
async def test_drain_handler_calls_service_and_returns_success():
    drained = []

    class _Svc:
        async def drain_due(self, *, now_ms): drained.append(now_ms)

    handler = build_outbox_drain_handler(_Svc(), now_ms=lambda: 4242)
    result = await handler(object())   # scheduler context unused in v1
    assert result.success is True
    assert drained == [4242]
