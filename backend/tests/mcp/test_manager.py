import pytest

from magi.mcp.config import MCPServerConfig
from magi.mcp.manager import MCPManager
from magi.tools.registry import ToolRegistry


class StubConnection:
    def __init__(self, tools, resources=None):
        self._tools = tools
        self._resources = resources or []
        self.started = False
        self._handlers = {}
        self.calls = []

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    def on_notification(self, method, handler):
        self._handlers.setdefault(method, []).append(handler)

    async def notify(self, method, params=None):
        self.calls.append(("notify", method, params))

    async def request(self, method, params, *, timeout):
        self.calls.append(("request", method, params))
        if method == "initialize":
            return {"protocolVersion": "2024-11-05", "capabilities": {}}
        if method == "tools/list":
            return {"tools": self._tools}
        if method == "resources/list":
            return {"resources": self._resources}
        if method == "tools/call":
            return {
                "content": [
                    {"type": "text", "text": f"ran {params['name']}"}
                ],
                "isError": False,
            }
        raise RuntimeError(f"unexpected {method}")


CFG = MCPServerConfig.model_validate(
    {
        "server": {"id": "demo", "name": "Demo", "autostart": True},
        "transport": {"kind": "stdio", "command": "x"},
    }
)


def _conn_with(tools, resources=None):
    holder = {}

    def factory(_cfg):
        c = StubConnection(tools, resources)
        holder["conn"] = c
        return c

    return factory, holder


@pytest.mark.asyncio
async def test_manager_registers_tools_after_handshake():
    registry = ToolRegistry()
    factory, h = _conn_with(
        [
            {
                "name": "echo",
                "description": "e",
                "inputSchema": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                },
            }
        ]
    )
    mgr = MCPManager(registry=registry, connection_factory=factory)
    mgr.add_config(CFG)
    await mgr.start_server("demo")

    assert registry.get_tool("mcp__demo__echo") is not None
    methods = [c[1] for c in h["conn"].calls if c[0] == "request"]
    assert "initialize" in methods
    assert "tools/list" in methods
    notifications = [c[1] for c in h["conn"].calls if c[0] == "notify"]
    assert "notifications/initialized" in notifications


@pytest.mark.asyncio
async def test_manager_unregisters_on_stop():
    registry = ToolRegistry()
    factory, _ = _conn_with(
        [
            {
                "name": "a",
                "description": "",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    mgr = MCPManager(registry=registry, connection_factory=factory)
    mgr.add_config(CFG)
    await mgr.start_server("demo")
    assert registry.get_tool("mcp__demo__a") is not None
    await mgr.stop_server("demo")
    assert registry.get_tool("mcp__demo__a") is None


@pytest.mark.asyncio
async def test_call_remote_routes_to_running_server():
    registry = ToolRegistry()
    factory, h = _conn_with(
        [
            {
                "name": "echo",
                "description": "e",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    mgr = MCPManager(registry=registry, connection_factory=factory)
    mgr.add_config(CFG)
    await mgr.start_server("demo")

    result = await mgr.call_remote("demo", "echo", {"a": 1}, 30000)
    assert result["isError"] is False
    call = next(c for c in h["conn"].calls if c[0] == "request" and c[1] == "tools/call")
    assert call[2] == {"name": "echo", "arguments": {"a": 1}}


@pytest.mark.asyncio
async def test_resources_listed_during_start():
    registry = ToolRegistry()
    factory, h = _conn_with(
        [],
        resources=[{"uri": "file:///x.txt", "name": "x", "mimeType": "text/plain"}],
    )
    mgr = MCPManager(registry=registry, connection_factory=factory)
    mgr.add_config(CFG)
    await mgr.start_server("demo")
    res = await mgr.list_resources()
    assert res == [
        {
            "server_id": "demo",
            "uri": "file:///x.txt",
            "name": "x",
            "mimeType": "text/plain",
        }
    ]


@pytest.mark.asyncio
async def test_disabled_server_refuses_start():
    cfg = MCPServerConfig.model_validate(
        {
            "server": {"id": "off", "name": "Off", "enabled": False},
            "transport": {"kind": "stdio", "command": "x"},
        }
    )
    factory, _ = _conn_with([])
    mgr = MCPManager(registry=ToolRegistry(), connection_factory=factory)
    mgr.add_config(cfg)
    with pytest.raises(RuntimeError, match="disabled"):
        await mgr.start_server("off")
