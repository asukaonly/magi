"""Tests for the /api/commands router."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from magi_plugin_sdk.tools import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

from magi.api.routers.commands import commands_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.commands.resolver import UserInvocableResolver
from magi.commands import resolver as resolver_mod
from magi.control.permission.contracts import PermissionDecision, PermissionOutcome


class _EchoTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(
            name="echo",
            description="Echo input",
            category="test",
            parameters=[
                ToolParameter(
                    name="text", type=ParameterType.STRING, description="", required=True
                ),
            ],
            metadata={"user_invocable": True},
        )

    async def execute(self, parameters, context):
        return ToolResult(success=True, data={"output": parameters["text"]})


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Stub tool_registry that the router imports.
    echo = _EchoTool()
    registry = MagicMock()
    registry.get_tool.side_effect = lambda name: echo if name == "echo" else None
    registry.list_tools.return_value = ["echo"]
    registry.get_tool_info.side_effect = lambda name: (
        echo.get_info() if name == "echo" else None
    )

    async def _execute(name, args, ctx):
        if name == "echo":
            return await echo.execute(args, ctx)
        raise KeyError(name)

    registry.execute = _execute

    from magi.api.routers import commands as commands_module
    monkeypatch.setattr(commands_module, "tool_registry", registry)

    # Force a clean resolver pinned at a tmp whitelist.
    resolver_mod._default_resolver = UserInvocableResolver(
        whitelist_path=tmp_path / "missing.toml"
    )

    # Stub chat transcript writer + permission gateway.
    class _FakeTranscriptWriter:
        appended: list = []

        async def append_command_invocation(self, **kwargs):
            record = SimpleNamespace(
                message_id=f"msg-{len(_FakeTranscriptWriter.appended) + 1}",
                message_kind="command_invocation",
                content_text=kwargs["invocation_text"] or f"/{kwargs['tool_name']}",
                turn_id=kwargs["turn_id"],
            )
            _FakeTranscriptWriter.appended.append(record)
            return record.message_id

        async def append_command_result(self, **kwargs):
            record = SimpleNamespace(
                message_id=f"msg-{len(_FakeTranscriptWriter.appended) + 1}",
                message_kind="command_result",
                content_text=kwargs["output_text"],
                turn_id=kwargs["turn_id"],
            )
            _FakeTranscriptWriter.appended.append(record)
            return record.message_id

    _FakeTranscriptWriter.appended = []
    monkeypatch.setattr(
        commands_module,
        "require_chat_surface_write_service",
        lambda: _FakeTranscriptWriter(),
    )
    class _AllowingGateway:
        async def gate(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return PermissionDecision(
                request_id="req_allow",
                outcome=PermissionOutcome.ALLOWED,
                source="test",
                reason="ok",
            )

    monkeypatch.setattr(
        commands_module,
        "_safe_gateway_provider",
        lambda: _AllowingGateway(),
    )

    app = FastAPI()
    app.include_router(_build_public_router(commands_router, _PUBLIC_ROUTE_METHODS["commands"]), prefix="/api/commands")
    yield TestClient(app), _FakeTranscriptWriter


def test_list_user_invocable_commands(client):
    c, _ = client
    r = c.get("/api/commands/")
    assert r.status_code == 200
    payload = r.json()
    echo = next(item for item in payload["data"] if item["name"] == "echo")
    assert echo["kind"] == "tool"
    assert echo["execution_owner"] == "command_runner"
    assert echo["description"] == "Echo input"
    assert {item["name"] for item in payload["data"]} >= {
        "auto",
        "fast",
        "deep",
        "clear",
    }
    cancel = next(item for item in payload["data"] if item["name"] == "cancel")
    assert cancel["visibility"] == "composer"
    fast = next(item for item in payload["data"] if item["name"] == "fast")
    assert fast["visibility"] == "composer"
    assert fast["reasoning_preference"] == "fast"


def test_public_router_exposes_only_current_command_contract() -> None:
    public = _build_public_router(
        commands_router,
        _PUBLIC_ROUTE_METHODS["commands"],
    )
    routes = {route.path for route in public.routes}

    assert routes == {"/", "/run", "/run-skill-as-background"}


@pytest.mark.asyncio
async def test_run_command_returns_result_and_persists(
    client, monkeypatch, runtime_paths_with_schema
):
    import json
    from magi.chat.store import ChatStore
    from magi.chat.surface_writes import ChatSurfaceWriteService
    from magi.chat import surface_writes
    from magi.api.routers import commands
    from unittest.mock import AsyncMock

    c, _ = client
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    monkeypatch.setattr(commands, "require_chat_surface_write_service", ChatSurfaceWriteService)
    monkeypatch.setattr(surface_writes, "get_chat_store", lambda: store)
    monkeypatch.setattr(
        surface_writes,
        "get_chat_message_notifier",
        lambda: SimpleNamespace(broadcast_chat_message_upsert=AsyncMock()),
    )
    try:
        response = c.post(
            "/api/commands/run",
            json={
                "session_id": "s1",
                "tool_name": "echo",
                "arguments": {"text": "hello"},
                "invocation_text": "/echo text=hello",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True
        assert response.json()["output"] == "hello"
        invocation, result = await store.list_messages(session_id="s1")
        assert (invocation.role, invocation.message_kind, invocation.content_text) == (
            "user",
            "command_invocation",
            "/echo text=hello",
        )
        assert (result.role, result.message_kind, result.content_text) == (
            "tool",
            "command_result",
            "hello",
        )
        assert invocation.turn_id == result.turn_id and invocation.turn_id
        assert invocation.user_id == result.user_id == "local_user"
        assert invocation.session_id == result.session_id == "s1"
        assert json.loads(invocation.payload_json) == {
            "command": {"tool_name": "echo", "arguments": {"text": "hello"}}
        }
        payload = json.loads(result.payload_json)["command_result"]
        assert payload["invocation_message_id"] == invocation.message_id
        assert payload["arguments"] == {"text": "hello"}
        assert payload["success"] is True and payload["error"] is None
        assert await store.list_messages(session_id="unrelated") == []
    finally:
        await store.shutdown()


def test_run_command_rejects_unknown_tool(client):
    c, _ = client
    r = c.post(
        "/api/commands/run",
        json={
            "session_id": "s1",
            "tool_name": "nope",
            "arguments": {},
            "invocation_text": "/nope",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] in (
        ToolErrorCode.PERMISSION_DENIED.value,
        ToolErrorCode.TOOL_NOT_FOUND.value,
    )
