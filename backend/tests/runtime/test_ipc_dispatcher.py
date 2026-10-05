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
    async def test_notifications_dispatch_exact_parameters_and_report_unknown_method(self, monkeypatch):
        from unittest.mock import AsyncMock, Mock
        import magi.ipc.dispatcher as module

        dispatcher = Dispatcher()
        handler = AsyncMock()
        dispatcher.register("echo", handler)
        warning = Mock()
        monkeypatch.setattr(module.logger, "warning", warning)
        await dispatcher.dispatch_notify(IpcNotify(method="echo", params={"x": 1}))
        handler.assert_awaited_once_with({"x": 1})
        warning.assert_not_called()
        await dispatcher.dispatch_notify(IpcNotify(method="unknown", params={"x": 2}))
        handler.assert_awaited_once_with({"x": 1})
        warning.assert_called_once_with("ipc_notify_no_handler", method="unknown")
