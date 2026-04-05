"""Tests for the IPC dispatcher."""

from __future__ import annotations

import pytest

from magi.ipc.dispatcher import Dispatcher, MethodNotFound
from magi.ipc.protocol import IpcNotify, IpcRequest


@pytest.fixture
def dispatcher() -> Dispatcher:
    d = Dispatcher()

    async def echo_handler(params: dict | None) -> dict:
        return {"echo": params}

    d.register("echo", echo_handler)
    return d


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_request_known(self, dispatcher: Dispatcher) -> None:
        req = IpcRequest(id="1", method="echo", params={"msg": "hi"})
        result = await dispatcher.dispatch_request(req)
        assert result == {"echo": {"msg": "hi"}}

    @pytest.mark.asyncio
    async def test_dispatch_request_unknown(self, dispatcher: Dispatcher) -> None:
        req = IpcRequest(id="2", method="nonexistent", params=None)
        with pytest.raises(MethodNotFound):
            await dispatcher.dispatch_request(req)

    @pytest.mark.asyncio
    async def test_dispatch_notify_known(self, dispatcher: Dispatcher) -> None:
        notify = IpcNotify(method="echo", params={"x": 1})
        await dispatcher.dispatch_notify(notify)  # should not raise

    @pytest.mark.asyncio
    async def test_dispatch_notify_unknown_logs(self, dispatcher: Dispatcher) -> None:
        notify = IpcNotify(method="unknown", params=None)
        await dispatcher.dispatch_notify(notify)  # should not raise, just log
