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
    assert payload["tools"] == {"include": None}
    assert payload["available_tools"] == [
        {
            "name": "echo",
            "description": "",
            "enabled": True,
            "available": True,
        }
    ]
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


def test_explicit_tool_include_controls_registration_and_round_trips(client, tmp_path):
    c, mgr = client
    body = {
        "server": {"id": "demo", "name": "Demo", "autostart": True},
        "transport": {"kind": "stdio", "command": "x"},
        "tools": {"include": []},
        "tool_overrides": {"echo": {"risk": "medium"}},
    }

    response = c.post("/api/mcp/servers", json=body)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["tool_count"] == 0
    assert payload["tools"] == {"include": []}
    assert payload["available_tools"][0]["name"] == "echo"
    assert payload["available_tools"][0]["enabled"] is False
    assert payload["tool_overrides"] == {"echo": {"risk": "medium"}}
    assert mgr._registry.get_tool("mcp__demo__echo") is None  # type: ignore[attr-defined]

    cfg_path = tmp_path / "config" / "mcp" / "demo.toml"
    config_text = cfg_path.read_text()
    assert "[tools]" in config_text
    assert "include = []" in config_text

    from magi.mcp.loader import MCPConfigLoader

    [loaded] = MCPConfigLoader(cfg_path.parent).load_all()
    assert loaded.tools.include == []
    assert loaded.tool_overrides["echo"].risk == "medium"


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


def test_patch_preserves_masked_http_header_values(client, tmp_path):
    c, mgr = client
    secret = "secret-token-123"
    create = {
        "server": {"id": "httpsrv", "name": "HTTP"},
        "transport": {
            "kind": "http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": f"Bearer {secret}"},
        },
    }
    created = c.post("/api/mcp/servers", json=create).json()

    update = {
        "server": {"id": "httpsrv", "name": "HTTP"},
        "transport": created["transport"],
        "runtime": created["runtime"],
        "tools": {"include": []},
    }
    response = c.patch("/api/mcp/servers/httpsrv", json=update)

    assert response.status_code == 200, response.text
    cfg = next(item for item in mgr.list_configs() if item.server.id == "httpsrv")
    assert cfg.transport.headers["Authorization"] == f"Bearer {secret}"
    config_text = (tmp_path / "config" / "mcp" / "httpsrv.toml").read_text()
    assert f"Bearer {secret}" in config_text
    assert 'Authorization = "***"' not in config_text


def test_stdio_transport_credentials_are_write_only(client, tmp_path):
    c, mgr = client
    secrets = {
        "env": "stdio-env-secret",
        "mode": "stdio-mode-value",
        "arg": "stdio-arg-secret",
        "url_user": "stdio-user",
        "url_password": "stdio-password",
        "url_token": "stdio-url-token",
    }
    body = {
        "server": {"id": "stdio-secrets", "name": "Stdio secrets"},
        "transport": {
            "kind": "stdio",
            "command": "example-mcp",
            "args": [
                "--api-key",
                secrets["arg"],
                (
                    "--endpoint=https://"
                    f"{secrets['url_user']}:{secrets['url_password']}@example.com/mcp"
                    f"?token={secrets['url_token']}&mode=read"
                ),
            ],
            "env": {"ACCESS_TOKEN": secrets["env"], "MODE": secrets["mode"]},
        },
    }

    response = c.post("/api/mcp/servers", json=body)

    assert response.status_code == 201, response.text
    transport = response.json()["transport"]
    assert transport["args"] == [
        "--api-key",
        "***",
        "--endpoint=https://***:***@example.com/mcp?token=***&mode=read",
    ]
    assert transport["env"] == {"ACCESS_TOKEN": "***", "MODE": "***"}
    assert all(secret not in response.text for secret in secrets.values())

    round_trip = {
        "server": {"id": "stdio-secrets", "name": "Stdio secrets"},
        "transport": transport,
        "runtime": response.json()["runtime"],
    }
    updated = c.patch("/api/mcp/servers/stdio-secrets", json=round_trip)
    assert updated.status_code == 200, updated.text
    config = next(item for item in mgr.list_configs() if item.server.id == "stdio-secrets")
    assert config.transport.args == body["transport"]["args"]
    assert config.transport.env == body["transport"]["env"]
    config_text = (tmp_path / "config" / "mcp" / "stdio-secrets.toml").read_text()
    assert secrets["arg"] in config_text
    assert secrets["env"] in config_text

    changed_target = {
        **round_trip,
        "transport": {**transport, "command": "different-mcp"},
    }
    rejected = c.patch("/api/mcp/servers/stdio-secrets", json=changed_target)
    assert rejected.status_code == 400
    assert "must be re-entered" in rejected.text

    replacement = {
        **round_trip,
        "transport": {
            "kind": "stdio",
            "command": "different-mcp",
            "args": ["--api-key", "new-arg-secret"],
            "cwd": "",
            "env": {"ACCESS_TOKEN": "new-env-secret", "MODE": "new-mode"},
        },
    }
    replaced = c.patch("/api/mcp/servers/stdio-secrets", json=replacement)
    assert replaced.status_code == 200, replaced.text
    assert "new-arg-secret" not in replaced.text
    assert "new-env-secret" not in replaced.text


def test_http_url_credentials_are_write_only_and_origin_bound(client, tmp_path):
    c, mgr = client
    body = {
        "server": {"id": "http-url-secrets", "name": "HTTP URL secrets"},
        "transport": {
            "kind": "http",
            "url": (
                "https://url-user:url-password@example.com/mcp"
                "?access_token=url-token&mode=read"
            ),
            "headers": {"Authorization": "Bearer header-secret"},
        },
    }

    response = c.post("/api/mcp/servers", json=body)

    assert response.status_code == 201, response.text
    transport = response.json()["transport"]
    assert transport["url"] == (
        "https://***:***@example.com/mcp?access_token=***&mode=read"
    )
    assert transport["headers"] == {"Authorization": "***"}
    for secret in ("url-user", "url-password", "url-token", "header-secret"):
        assert secret not in response.text

    round_trip = {
        "server": {"id": "http-url-secrets", "name": "HTTP URL secrets"},
        "transport": transport,
        "runtime": response.json()["runtime"],
    }
    updated = c.patch("/api/mcp/servers/http-url-secrets", json=round_trip)
    assert updated.status_code == 200, updated.text
    config = next(item for item in mgr.list_configs() if item.server.id == "http-url-secrets")
    assert config.transport.url == body["transport"]["url"]
    assert config.transport.headers == body["transport"]["headers"]
    config_text = (tmp_path / "config" / "mcp" / "http-url-secrets.toml").read_text()
    assert "url-password" in config_text
    assert "header-secret" in config_text

    changed_origin = {
        **round_trip,
        "transport": {
            "kind": "http",
            "url": "https://other.example/mcp",
            "headers": {"Authorization": "***"},
        },
    }
    rejected = c.patch("/api/mcp/servers/http-url-secrets", json=changed_origin)
    assert rejected.status_code == 400
    assert "must be re-entered" in rejected.text


def test_create_rejects_masked_mcp_credentials_without_stored_values(client):
    c, _ = client
    response = c.post(
        "/api/mcp/servers",
        json={
            "server": {"id": "masked-create", "name": "Masked create"},
            "transport": {
                "kind": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "***"},
            },
        },
    )

    assert response.status_code == 400


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
