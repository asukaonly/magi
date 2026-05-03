import asyncio
import pytest
from magi.mcp.connection import MCPConnection, ConnectionState
from magi.mcp.protocol import JsonRpcResponse, JsonRpcNotification, JsonRpcError


class FakeTransport(MCPConnection):
    """In-memory transport for testing the request lock-step."""

    def __init__(self):
        super().__init__()
        self.outbox: list = []

    async def _start_transport(self):
        self.state = ConnectionState.CONNECTED

    async def _stop_transport(self):
        self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg):
        self.outbox.append(msg)

    async def deliver(self, msg):
        await self._dispatch(msg)


@pytest.mark.asyncio
async def test_request_resolves_on_matching_response():
    t = FakeTransport()
    await t.start()
    task = asyncio.create_task(t.request("ping", None, timeout=1.0))
    await asyncio.sleep(0)
    sent = t.outbox[0]
    await t.deliver(JsonRpcResponse(id=sent.id, result={"ok": True}))
    res = await task
    assert res == {"ok": True}


@pytest.mark.asyncio
async def test_request_propagates_server_error():
    t = FakeTransport()
    await t.start()
    task = asyncio.create_task(t.request("oops", None, timeout=1.0))
    await asyncio.sleep(0)
    sent = t.outbox[0]
    await t.deliver(
        JsonRpcResponse(id=sent.id, error=JsonRpcError(code=-1, message="boom"))
    )
    with pytest.raises(RuntimeError, match="boom"):
        await task


@pytest.mark.asyncio
async def test_request_times_out():
    t = FakeTransport()
    await t.start()
    with pytest.raises(asyncio.TimeoutError):
        await t.request("slow", None, timeout=0.05)


@pytest.mark.asyncio
async def test_notifications_dispatched_to_handlers():
    t = FakeTransport()
    seen = []
    t.on_notification("notifications/x", lambda p: seen.append(p))
    await t.start()
    await t.deliver(JsonRpcNotification(method="notifications/x", params={"v": 1}))
    assert seen == [{"v": 1}]


@pytest.mark.asyncio
async def test_stop_fails_pending_requests():
    t = FakeTransport()
    await t.start()
    task = asyncio.create_task(t.request("never", None, timeout=10.0))
    await asyncio.sleep(0)
    await t.stop()
    with pytest.raises(ConnectionError):
        await task
