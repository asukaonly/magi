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
    app.include_router(commands_router, prefix="/api/commands")
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


def test_run_command_returns_result_and_persists(client):
    c, store_cls = client
    r = c.post(
        "/api/commands/run",
        json={
            "session_id": "s1",
            "tool_name": "echo",
            "arguments": {"text": "hello"},
            "invocation_text": "/echo text=hello",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["output"] == "hello"
    # 2 messages: invocation + result
    assert len(store_cls.appended) == 2


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
