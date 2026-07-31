"""REST API tests for the MCP router.

Mounts the router directly on a fresh FastAPI app and uses a stub
MCPConnection so tests don't depend on real subprocess MCP servers.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.mcp import mcp_router
from magi.mcp import lifecycle as mcp_lifecycle
from magi.mcp.connection import ConnectionState, MCPConnection
from magi.mcp.manager import MCPManager
from magi.mcp.protocol import JsonRpcRequest, JsonRpcResponse
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import set_runtime_dir
from magi.utils import runtime as rt_mod


class _StubConn(MCPConnection):
    """Minimal in-memory MCPConnection that auto-replies to standard MCP RPCs."""

    def __init__(self, tools=None, resources=None):
        super().__init__()
        self._tools = tools or []
        self._resources = resources or []

    async def _start_transport(self):
        self.state = ConnectionState.CONNECTED

    async def _stop_transport(self):
        self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg):
        if not isinstance(msg, JsonRpcRequest):
            return
        if msg.method == "initialize":
            await self._dispatch(JsonRpcResponse(
                id=msg.id,
                result={
                    "protocolVersion": "x",
                    "capabilities": {"tools": {}, "resources": {}},
                },
            ))
        elif msg.method == "tools/list":
            await self._dispatch(JsonRpcResponse(id=msg.id, result={"tools": self._tools}))
        elif msg.method == "resources/list":
            await self._dispatch(JsonRpcResponse(id=msg.id, result={"resources": self._resources}))
        elif msg.method == "resources/templates/list":
            await self._dispatch(JsonRpcResponse(id=msg.id, result={"resourceTemplates": []}))
        elif msg.method == "resources/read":
            await self._dispatch(
                JsonRpcResponse(
                    id=msg.id,
                    result={
                        "contents": [
                            {
                                "uri": (msg.params or {}).get("uri"),
                                "mimeType": "text/plain",
                                "text": "hello",
                            }
                        ]
                    },
                )
            )


@pytest.fixture
def client(tmp_path, monkeypatch):
    set_runtime_dir(tmp_path)
    registry = ToolRegistry()

    def _factory(_cfg):
        return _StubConn(
            tools=[
                {
                    "name": "echo",
                    "description": "",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ],
            resources=[
                {"uri": "file:///x.txt", "name": "x", "mimeType": "text/plain"}
            ],
        )

    manager = MCPManager(registry=registry, connection_factory=_factory)
    monkeypatch.setattr(mcp_lifecycle, "_active_manager", manager)

    app = FastAPI()
    app.include_router(mcp_router, prefix="/api/mcp")
    yield TestClient(app), manager

    monkeypatch.setattr(mcp_lifecycle, "_active_manager", None)
    rt_mod._runtime_paths = None


def test_list_servers_empty(client):
    c, _ = client
    r = c.get("/api/mcp/servers")
    assert r.status_code == 200
    assert r.json() == {"data": []}


def test_create_then_list_then_delete_server(client, tmp_path):
    c, mgr = client
    body = {
        "server": {"id": "demo", "name": "Demo", "autostart": True},
        "transport": {"kind": "stdio", "command": "x"},
    }
    r = c.post("/api/mcp/servers", json=body)
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["id"] == "demo"
    assert payload["state"] == "connected"
    assert payload["tool_count"] == 1
    assert payload["resource_count"] == 1

    cfg_path = tmp_path / "config" / "mcp" / "demo.toml"
    assert cfg_path.exists()
    body_text = cfg_path.read_text()
    assert 'id = "demo"' in body_text
    assert "autostart = true" in body_text
    # And the file must be loadable round-trip
    from magi.mcp.loader import MCPConfigLoader
    cfgs = MCPConfigLoader(cfg_path.parent).load_all()
    assert cfgs[0].server.autostart is True

    r = c.get("/api/mcp/servers")
    assert len(r.json()["data"]) == 1

    r = c.delete("/api/mcp/servers/demo")
    assert r.status_code == 204
    assert not cfg_path.exists()
    assert mgr.is_running("demo") is False


def test_create_rejects_duplicate_id(client):
    c, _ = client
    body = {
        "server": {"id": "demo", "name": "Demo"},
        "transport": {"kind": "stdio", "command": "x"},
    }
    assert c.post("/api/mcp/servers", json=body).status_code == 201
    r = c.post("/api/mcp/servers", json=body)
    assert r.status_code == 409


def test_start_and_stop_endpoints(client):
    c, mgr = client
    body = {
        "server": {"id": "demo", "name": "Demo"},  # autostart default false
        "transport": {"kind": "stdio", "command": "x"},
    }
    r = c.post("/api/mcp/servers", json=body)
    assert r.status_code == 201
    assert r.json()["state"] == "disconnected"

    r = c.post("/api/mcp/servers/demo/start")
    assert r.status_code == 200
    assert r.json()["state"] == "connected"
    assert mgr.is_running("demo")

    r = c.post("/api/mcp/servers/demo/stop")
    assert r.status_code == 200
    assert r.json()["state"] == "disconnected"
    assert not mgr.is_running("demo")


def test_resources_listed_and_read(client):
    c, _ = client
    body = {
        "server": {"id": "demo", "name": "Demo", "autostart": True},
        "transport": {"kind": "stdio", "command": "x"},
    }
    c.post("/api/mcp/servers", json=body)

    r = c.get("/api/mcp/resources")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data == [
        {
            "server_id": "demo",
            "uri": "file:///x.txt",
            "name": "x",
            "mimeType": "text/plain",
        }
    ]

    r = c.post(
        "/api/mcp/resources/read",
        json={"server_id": "demo", "uri": "file:///x.txt"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contents"][0]["text"] == "hello"


def test_resource_read_requires_running_server(client):
    c, _ = client
    body = {
        "server": {"id": "demo", "name": "Demo"},
        "transport": {"kind": "stdio", "command": "x"},
    }
    c.post("/api/mcp/servers", json=body)
    r = c.post(
        "/api/mcp/resources/read",
        json={"server_id": "demo", "uri": "file:///x.txt"},
    )
    assert r.status_code == 400


def test_logs_endpoint_returns_empty_when_not_running(client):
    c, _ = client
    body = {
        "server": {"id": "demo", "name": "Demo"},
        "transport": {"kind": "stdio", "command": "x"},
    }
    c.post("/api/mcp/servers", json=body)
    r = c.get("/api/mcp/servers/demo/logs")
    assert r.status_code == 200
    assert r.json() == {"server_id": "demo", "stderr": [], "last_error": None}


def test_mcp_status_and_logs_redact_arbitrary_configured_values(client):
    c, mgr = client
    secret = "mcp-router-custom-secret"
    body = {
        "server": {"id": "demo", "name": "Demo", "autostart": True},
        "transport": {
            "kind": "stdio",
            "command": "x",
            "env": {"UNUSUAL_SETTING": secret},
        },
    }
    assert c.post("/api/mcp/servers", json=body).status_code == 201
    mgr._runtimes["demo"].last_error = f"failed with {secret}"  # type: ignore[attr-defined]

    status_payload = c.get("/api/mcp/servers").json()["data"][0]
    logs_payload = c.get("/api/mcp/servers/demo/logs").json()

    assert secret not in str(logs_payload)
    assert status_payload["last_error"] == "failed with [REDACTED]"
    assert logs_payload["last_error"] == "failed with [REDACTED]"


def test_patch_updates_and_restarts(client):
    c, mgr = client
    body = {
        "server": {"id": "demo", "name": "Demo", "autostart": True},
        "transport": {"kind": "stdio", "command": "x"},
    }
    c.post("/api/mcp/servers", json=body)
    assert mgr.is_running("demo")

    update = {
        "server": {"id": "demo", "name": "Demo Renamed"},
        "transport": {"kind": "stdio", "command": "y", "args": ["--flag"]},
    }
    r = c.patch("/api/mcp/servers/demo", json=update)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Demo Renamed"
    assert body["state"] == "connected"
    assert body["transport"]["args"] == ["--flag"]


def test_http_transport_headers_masked_in_responses(client):
    c, _ = client
    body = {
        "server": {"id": "httpsrv", "name": "HTTP"},
        "transport": {
            "kind": "http",
            "url": "https://example.com/mcp",
            "headers": {
                "Authorization": "Bearer secret-token-123",
                "X-Empty": "",
            },
        },
    }
    r = c.post("/api/mcp/servers", json=body)
    assert r.status_code == 201, r.text
    payload = r.json()
    # Header names visible, values masked.
    assert payload["transport"]["headers"]["Authorization"] == "***"
    # Empty values stay empty.
    assert payload["transport"]["headers"]["X-Empty"] == ""
    # Secret must not appear anywhere in response body.
    assert "secret-token-123" not in r.text

    # Also masked on listing.
    r = c.get("/api/mcp/servers")
    assert r.status_code == 200
    assert "secret-token-123" not in r.text
    listed = r.json()["data"][0]
    assert listed["transport"]["headers"]["Authorization"] == "***"

    # Single-server endpoints (start/stop) also mask.
    r = c.post("/api/mcp/servers/httpsrv/stop")
    assert r.status_code == 200
    assert "secret-token-123" not in r.text
    assert r.json()["transport"]["headers"]["Authorization"] == "***"


def test_404_when_unknown_server(client):
    c, _ = client
    assert c.post("/api/mcp/servers/nope/start").status_code == 404
    assert c.post("/api/mcp/servers/nope/stop").status_code == 404
    assert c.delete("/api/mcp/servers/nope").status_code == 404
    assert c.patch(
        "/api/mcp/servers/nope",
        json={
            "server": {"id": "nope", "name": "x"},
            "transport": {"kind": "stdio", "command": "x"},
        },
    ).status_code == 404
