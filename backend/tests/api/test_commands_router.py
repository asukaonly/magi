"""Tests for the /api/commands router."""

from unittest.mock import AsyncMock, MagicMock

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
from magi.commands.resolver import UserInvocableResolver
from magi.commands import resolver as resolver_mod


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

    # Stub chat store + permission gateway + notifier.
    class _FakeStore:
        appended: list = []

        async def append_message(self, record, **kwargs):
            _FakeStore.appended.append(record)

    from magi.commands import runner as runner_mod
    monkeypatch.setattr(runner_mod, "get_chat_store", lambda: _FakeStore())
    _FakeStore.appended = []

    monkeypatch.setattr(commands_module, "_resolve_notifier", lambda: None)
    monkeypatch.setattr(commands_module, "_safe_gateway_provider", lambda: None)

    app = FastAPI()
    app.include_router(commands_router, prefix="/api/commands")
    yield TestClient(app), _FakeStore


def test_list_user_invocable_commands(client):
    c, _ = client
    r = c.get("/api/commands/")
    assert r.status_code == 200
    payload = r.json()
    assert payload["data"][0]["name"] == "echo"
    assert payload["data"][0]["description"] == "Echo input"


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


def test_resolve_notifier_returns_callable_with_valid_store(monkeypatch):
    """Regression: _resolve_notifier must build a real ChatRuntimeNotifier.

    The notifier module relocated to magi.chat.task_agent.postprocess in P2
    Task 2. The old import path under magi.agent.task_agents.handlers lives inside a
    ``try/except Exception: return None`` block, so a stale path silently
    disabled the notifier instead of raising. With a valid (non-``object``)
    runtime_trace_store wired in, _resolve_notifier must return a callable.
    """
    from magi.api.routers import commands as commands_module
    from magi.core import container as container_module

    class _FakeStore:  # not the bare ``object`` sentinel the guard rejects
        pass

    class _FakeContainer:
        runtime_trace_store = staticmethod(lambda: _FakeStore())

    # _resolve_notifier imports get_container locally, so patch it at source.
    monkeypatch.setattr(
        container_module, "get_container", lambda: _FakeContainer()
    )

    notifier = commands_module._resolve_notifier()

    assert notifier is not None
    assert callable(notifier)
