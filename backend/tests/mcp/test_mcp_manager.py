import pytest

from magi.mcp.config import MCPServerConfig
from magi.mcp.connection import ConnectionState
from magi.mcp.manager import MCPManager
from magi.tools.registry import ToolRegistry


class StubConnection:
    def __init__(
        self,
        tools,
        resources=None,
        resource_templates=None,
        prompts=None,
        page_size: int | None = None,
    ):
        self._tools = tools
        self._resources = resources or []
        self._resource_templates = resource_templates or []
        self._prompts = prompts or []
        self._page_size = page_size
        self.started = False
        self.state = ConnectionState.INIT
        self._handlers = {}
        self.calls = []

    async def start(self):
        self.started = True
        self.state = ConnectionState.CONNECTED

    async def stop(self):
        self.started = False
        self.state = ConnectionState.DISCONNECTED

    def on_notification(self, method, handler):
        self._handlers.setdefault(method, []).append(handler)

    async def notify(self, method, params=None):
        self.calls.append(("notify", method, params))

    def _paginate(self, items, key, params):
        if self._page_size is None:
            return {key: items}
        cursor = (params or {}).get("cursor")
        start = int(cursor) if cursor is not None else 0
        end = start + self._page_size
        page = items[start:end]
        result = {key: page}
        if end < len(items):
            result["nextCursor"] = str(end)
        return result

    async def request(self, method, params, *, timeout):
        self.calls.append(("request", method, params))
        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
            }
        if method == "tools/list":
            return self._paginate(self._tools, "tools", params)
        if method == "resources/list":
            return self._paginate(self._resources, "resources", params)
        if method == "resources/templates/list":
            return self._paginate(
                self._resource_templates, "resourceTemplates", params
            )
        if method == "prompts/list":
            return self._paginate(self._prompts, "prompts", params)
        if method == "tools/call":
            return {
                "content": [
                    {"type": "text", "text": f"ran {params['name']}"}
                ],
                "isError": False,
            }
        if method == "prompts/get":
            return {
                "description": "",
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": params["name"]},
                    }
                ],
            }
        raise RuntimeError(f"unexpected {method}")


CFG = MCPServerConfig.model_validate(
    {
        "server": {"id": "demo", "name": "Demo", "autostart": True},
        "transport": {"kind": "stdio", "command": "x"},
    }
)


def _conn_with(
    tools,
    resources=None,
    resource_templates=None,
    prompts=None,
    page_size=None,
):
    holder = {}

    def factory(_cfg):
        c = StubConnection(
            tools,
            resources,
            resource_templates,
            prompts,
            page_size=page_size,
        )
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
async def test_manager_registers_only_explicitly_included_tools():
    registry = ToolRegistry()
    factory, _ = _conn_with(
        [
            {
                "name": name,
                "description": name,
                "inputSchema": {"type": "object", "properties": {}},
            }
            for name in ("read", "write", "delete")
        ]
    )
    cfg = MCPServerConfig.model_validate(
        {
            "server": {"id": "filtered", "name": "Filtered"},
            "transport": {"kind": "stdio", "command": "x"},
            "tools": {"include": ["read"]},
        }
    )
    mgr = MCPManager(registry=registry, connection_factory=factory)
    mgr.add_config(cfg)

    await mgr.start_server("filtered")

    assert registry.get_tool("mcp__filtered__read") is not None
    assert registry.get_tool("mcp__filtered__write") is None
    assert registry.get_tool("mcp__filtered__delete") is None
    assert [tool["name"] for tool in mgr._runtimes["filtered"].tools] == [
        "read",
        "write",
        "delete",
    ]


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


@pytest.mark.asyncio
async def test_paginated_list_collects_all_pages():
    registry = ToolRegistry()
    tools = [
        {
            "name": f"t{i}",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }
        for i in range(7)
    ]
    resources = [
        {"uri": f"test://r/{i}", "name": f"r{i}", "mimeType": "text/plain"}
        for i in range(25)
    ]
    prompts = [{"name": f"p{i}", "description": ""} for i in range(12)]
    factory, h = _conn_with(
        tools,
        resources=resources,
        prompts=prompts,
        page_size=3,
    )
    mgr = MCPManager(registry=registry, connection_factory=factory)
    mgr.add_config(CFG)
    await mgr.start_server("demo")

    # All tools registered across pages.
    for i in range(7):
        assert registry.get_tool(f"mcp__demo__t{i}") is not None

    # Resources fully collected.
    res = await mgr.list_resources()
    assert len(res) == 25

    # Prompts fully collected.
    prs = await mgr.list_prompts()
    assert len(prs) == 12

    # Verify a cursor was actually used (multi-page).
    resource_calls = [
        c for c in h["conn"].calls
        if c[0] == "request" and c[1] == "resources/list"
    ]
    assert len(resource_calls) >= 2
    assert any(c[2] and "cursor" in c[2] for c in resource_calls)


@pytest.mark.asyncio
async def test_prompt_get_routes_to_running_server():
    registry = ToolRegistry()
    factory, h = _conn_with(
        [],
        prompts=[{"name": "greet", "description": "say hi"}],
    )
    mgr = MCPManager(registry=registry, connection_factory=factory)
    mgr.add_config(CFG)
    await mgr.start_server("demo")

    result = await mgr.get_prompt("demo", "greet", {"who": "world"})
    assert result["messages"][0]["content"]["text"] == "greet"
    call = next(
        c for c in h["conn"].calls if c[0] == "request" and c[1] == "prompts/get"
    )
    assert call[2] == {"name": "greet", "arguments": {"who": "world"}}
