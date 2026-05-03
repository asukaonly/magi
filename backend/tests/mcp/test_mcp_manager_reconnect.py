import asyncio

import pytest

from magi.mcp.config import MCPServerConfig
from magi.mcp.connection import ConnectionState, MCPConnection
from magi.mcp.manager import MCPManager
from magi.tools.registry import ToolRegistry


class _ControllableConn(MCPConnection):
    """Stub connection whose state can be flipped to DISCONNECTED on demand."""

    def __init__(self, tools):
        super().__init__()
        self._tools = tools

    async def _start_transport(self):
        self.state = ConnectionState.CONNECTED

    async def _stop_transport(self):
        self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg):
        # Auto-reply to requests with canned responses.
        from magi.mcp.protocol import (
            JsonRpcRequest,
            JsonRpcResponse,
        )

        if not isinstance(msg, JsonRpcRequest):
            return
        if msg.method == "initialize":
            await self._dispatch(
                JsonRpcResponse(id=msg.id, result={"protocolVersion": "x"})
            )
        elif msg.method == "tools/list":
            await self._dispatch(
                JsonRpcResponse(id=msg.id, result={"tools": self._tools})
            )
        elif msg.method == "resources/list":
            await self._dispatch(
                JsonRpcResponse(id=msg.id, result={"resources": []})
            )

    def trigger_disconnect(self):
        self.state = ConnectionState.DISCONNECTED


CFG = MCPServerConfig.model_validate(
    {
        "server": {"id": "demo", "name": "Demo"},
        "transport": {"kind": "stdio", "command": "x"},
        "runtime": {"max_restart_attempts": 2},
    }
)


@pytest.mark.asyncio
async def test_unregisters_on_disconnect_and_reregisters_after_reconnect():
    registry = ToolRegistry()
    tools = [
        {
            "name": "ping",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    conns: list[_ControllableConn] = []

    def factory(_cfg):
        c = _ControllableConn(tools)
        conns.append(c)
        return c

    mgr = MCPManager(
        registry=registry,
        connection_factory=factory,
        reconnect_backoff=[0.01, 0.01],
    )
    mgr.add_config(CFG)
    await mgr.start_server("demo")
    assert registry.get_tool("mcp__demo__ping") is not None

    conns[0].trigger_disconnect()

    # Watchdog tick + reconnect
    for _ in range(50):
        await asyncio.sleep(0.02)
        if len(conns) >= 2 and registry.get_tool("mcp__demo__ping") is not None:
            break
    assert len(conns) >= 2
    assert registry.get_tool("mcp__demo__ping") is not None
    await mgr.stop_server("demo")


@pytest.mark.asyncio
async def test_gives_up_after_max_restart_attempts():
    registry = ToolRegistry()

    class _AlwaysDead(_ControllableConn):
        async def _start_transport(self):
            self.state = ConnectionState.DISCONNECTED  # immediately dead

    started_count = {"n": 0}

    def factory(_cfg):
        if started_count["n"] == 0:
            started_count["n"] += 1
            return _ControllableConn([])
        started_count["n"] += 1
        return _AlwaysDead([])

    mgr = MCPManager(
        registry=registry,
        connection_factory=factory,
        reconnect_backoff=[0.01, 0.01],
    )
    mgr.add_config(CFG)
    await mgr.start_server("demo")
    # First conn is alive; trigger disconnect; subsequent attempts fail.
    rt_conn = mgr._runtimes["demo"].conn  # type: ignore[attr-defined]
    rt_conn.state = ConnectionState.DISCONNECTED
    # Wait for retries to be exhausted (max 2 attempts in CFG)
    for _ in range(100):
        await asyncio.sleep(0.02)
        if started_count["n"] >= 1 + 2:
            break
    # After exhaustion, runtime should be gone.
    for _ in range(50):
        await asyncio.sleep(0.02)
        if "demo" not in mgr._runtimes:  # type: ignore[attr-defined]
            break
    assert "demo" not in mgr._runtimes  # type: ignore[attr-defined]
