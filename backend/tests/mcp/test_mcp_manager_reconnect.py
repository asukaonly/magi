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
                JsonRpcResponse(
                    id=msg.id,
                    result={
                        "protocolVersion": "x",
                        "capabilities": {
                            "tools": {},
                            "resources": {},
                            "prompts": {},
                        },
                    },
                )
            )
        elif msg.method == "tools/list":
            await self._dispatch(
                JsonRpcResponse(id=msg.id, result={"tools": self._tools})
            )
        elif msg.method == "resources/list":
            await self._dispatch(
                JsonRpcResponse(id=msg.id, result={"resources": []})
            )
        elif msg.method == "resources/templates/list":
            await self._dispatch(
                JsonRpcResponse(id=msg.id, result={"resourceTemplates": []})
            )
        elif msg.method == "prompts/list":
            await self._dispatch(
                JsonRpcResponse(id=msg.id, result={"prompts": []})
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
    reconnect_entered = asyncio.Event()
    release = asyncio.Event()

    class GatedConnection(_ControllableConn):
        async def _start_transport(self):
            reconnect_entered.set()
            await release.wait()
            await super()._start_transport()

    connections = []

    def factory(config):
        name = "old" if not connections else "new"
        cls = _ControllableConn if not connections else GatedConnection
        connection = cls(
            [{"name": name, "description": "", "inputSchema": {"type": "object", "properties": {}}}]
        )
        connections.append(connection)
        return connection

    manager = MCPManager(registry=registry, connection_factory=factory, reconnect_backoff=[0.01])
    manager.add_config(CFG)
    try:
        await manager.start_server("demo")
        assert registry.get_tool("mcp__demo__old") is not None
        connections[0].trigger_disconnect()
        await asyncio.wait_for(reconnect_entered.wait(), 2)
        assert registry.get_tool("mcp__demo__old") is None
        assert registry.get_tool("mcp__demo__new") is None
        release.set()

        async def wait_for_new_catalog():
            while registry.get_tool("mcp__demo__new") is None:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_new_catalog(), 2)
        assert len(connections) == 2
        assert registry.get_tool("mcp__demo__old") is None
        assert registry.get_tool("mcp__demo__new") is not None
    finally:
        release.set()
        await manager.stop_all()
    assert registry.get_tool("mcp__demo__new") is None


@pytest.mark.asyncio
async def test_partially_started_connection_stopped_on_watchdog_cancel():
    """If the watchdog is cancelled mid-`new_conn.start()`, the new connection
    must still be stopped to avoid orphaning a subprocess/socket."""
    registry = ToolRegistry()

    blocking_started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingConn(_ControllableConn):
        def __init__(self, tools):
            super().__init__(tools)
            self.stopped = False

        async def _start_transport(self):
            blocking_started.set()
            await release.wait()
            self.state = ConnectionState.CONNECTED

        async def _stop_transport(self):
            self.stopped = True
            self.state = ConnectionState.DISCONNECTED

    blocking_conns: list[_BlockingConn] = []
    call_count = {"n": 0}

    def factory(_cfg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: ordinary alive conn for initial start.
            return _ControllableConn([])
        # Subsequent (reconnect) call: blocking conn we control.
        c = _BlockingConn([])
        blocking_conns.append(c)
        return c

    mgr = MCPManager(
        registry=registry,
        connection_factory=factory,
        reconnect_backoff=[0.0, 0.0],
    )
    mgr.add_config(CFG)
    await mgr.start_server("demo")
    rt = mgr._runtimes["demo"]  # type: ignore[attr-defined]

    # Trigger disconnect so watchdog enters reconnect path.
    rt.conn.state = ConnectionState.DISCONNECTED

    # Wait until the new (blocking) connection's start is in-flight.
    await asyncio.wait_for(blocking_started.wait(), timeout=2.0)

    # Cancel the watchdog while start() is still pending.
    rt.watchdog.cancel()
    # Allow start() to proceed past the wait so the cancellation can land.
    release.set()
    try:
        await rt.watchdog
    except asyncio.CancelledError:
        pass

    assert blocking_conns, "blocking reconnect conn never created"
    assert blocking_conns[-1].stopped is True


@pytest.mark.asyncio
async def test_max_restart_attempts_beyond_backoff_length(monkeypatch):
    """A user-configured max_restart_attempts greater than the backoff array
    must be honored; the last backoff value is repeated for extra attempts."""
    registry = ToolRegistry()

    class _DeadConn(_ControllableConn):
        async def _start_transport(self):
            self.state = ConnectionState.DISCONNECTED

    starts = {"n": 0}

    def factory(_cfg):
        starts["n"] += 1
        if starts["n"] == 1:
            return _ControllableConn([])
        return _DeadConn([])

    cfg = MCPServerConfig.model_validate(
        {
            "server": {"id": "demo", "name": "Demo"},
            "transport": {"kind": "stdio", "command": "x"},
            "runtime": {"max_restart_attempts": 8},
        }
    )

    mgr = MCPManager(
        registry=registry,
        connection_factory=factory,
        reconnect_backoff=[0.0, 0.0, 0.0, 0.0, 0.0],  # 5 entries; cfg asks for 8
    )
    mgr.add_config(cfg)

    # Patch asyncio.sleep used inside manager to be near-instant so we don't
    # actually wait 30s on the repeated tail value.
    import magi.mcp.manager as mgr_mod

    real_sleep = asyncio.sleep

    async def fast_sleep(_delay):
        await real_sleep(0)

    monkeypatch.setattr(mgr_mod.asyncio, "sleep", fast_sleep)

    await mgr.start_server("demo")
    mgr._runtimes["demo"].conn.state = ConnectionState.DISCONNECTED  # type: ignore[attr-defined]

    # Wait for runtime to be dropped after exhaustion.
    for _ in range(200):
        await real_sleep(0.01)
        if "demo" not in mgr._runtimes:  # type: ignore[attr-defined]
            break

    assert "demo" not in mgr._runtimes  # type: ignore[attr-defined]
    # 1 initial start + 8 reconnect attempts = 9 factory calls.
    assert starts["n"] == 1 + 8, f"expected 9 starts, got {starts['n']}"
