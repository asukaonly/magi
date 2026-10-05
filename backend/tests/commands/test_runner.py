"""Tests for CommandRunner."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from magi_plugin_sdk.tools import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

from magi.commands.runner import CommandRunner
from magi.commands.resolver import UserInvocableResolver
from magi.control.permission.contracts import PermissionDecision, PermissionOutcome


class _AllowingGateway:
    async def gate(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return PermissionDecision(
            request_id="req_allow",
            outcome=PermissionOutcome.ALLOWED,
            source="test",
            reason="ok",
        )


class _EchoTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(
            name="echo",
            description="echo",
            category="test",
            parameters=[
                ToolParameter(
                    name="text",
                    type=ParameterType.STRING,
                    description="",
                    required=True,
                ),
            ],
            metadata={"user_invocable": True},
        )

    async def execute(self, parameters, context):
        return ToolResult(success=True, data={"output": parameters.get("text", "")})


class _DangerousTool(Tool):
    def _init_schema(self):
        self.schema = ToolSchema(
            name="rm",
            description="rm",
            category="test",
            dangerous=True,
            metadata={"user_invocable": True},
        )

    async def execute(self, parameters, context):
        return ToolResult(success=True, data={"output": "wiped"})


def _build_registry(tools: list[Tool]) -> MagicMock:
    by_name = {t.get_schema().name: t for t in tools}
    registry = MagicMock()
    registry.get_tool.side_effect = lambda name: by_name.get(name)
    registry.list_tools.return_value = list(by_name.keys())
    registry.get_tool_info.side_effect = lambda name: (
        by_name[name].get_info() if name in by_name else None
    )

    async def _execute(name, args, ctx):
        return await by_name[name].execute(args, ctx)

    registry.execute = _execute
    return registry


@pytest.fixture(autouse=True)
def _stub_chat_store(monkeypatch):
    appended: list = []

    class _FakeTranscriptWriter:
        async def append_command_invocation(self, **kwargs):
            record = SimpleNamespace(
                message_id=f"msg-{len(appended) + 1}",
                message_kind="command_invocation",
                content_text=kwargs["invocation_text"] or f"/{kwargs['tool_name']}",
                turn_id=kwargs["turn_id"],
            )
            appended.append(record)
            return record.message_id

        async def append_command_result(self, **kwargs):
            record = SimpleNamespace(
                message_id=f"msg-{len(appended) + 1}",
                message_kind="command_result",
                content_text=kwargs["output_text"],
                turn_id=kwargs["turn_id"],
            )
            appended.append(record)
            return record.message_id

    fake = _FakeTranscriptWriter()
    from magi.commands import runner as runner_mod
    monkeypatch.setattr(runner_mod, "require_chat_surface_write_service", lambda: fake)
    yield appended


@pytest.fixture
def resolver(tmp_path):
    return UserInvocableResolver(whitelist_path=tmp_path / "missing.toml")


@pytest.mark.asyncio
async def test_writes_invocation_then_result(_stub_chat_store, resolver):
    registry = _build_registry([_EchoTool()])
    runner = CommandRunner(
        registry=registry,
        resolver=resolver,
        permission_gateway_provider=lambda: _AllowingGateway(),
    )
    result = await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="echo",
        arguments={"text": "hi"},
        invocation_text="/echo text=hi",
    )
    assert result.success
    assert result.output_text == "hi"
    assert len(_stub_chat_store) == 2
    assert _stub_chat_store[0].message_kind == "command_invocation"
    assert _stub_chat_store[0].content_text == "/echo text=hi"
    assert _stub_chat_store[1].message_kind == "command_result"
    assert _stub_chat_store[1].content_text == "hi"
    # turn_id is consistent across the pair
    assert _stub_chat_store[0].turn_id == _stub_chat_store[1].turn_id


@pytest.mark.asyncio
async def test_rejects_non_user_invocable(_stub_chat_store, resolver):
    """Tool without user_invocable metadata + not in whitelist → permission denied."""

    class _Plain(Tool):
        def _init_schema(self):
            self.schema = ToolSchema(name="plain", description="", category="test")

        async def execute(self, parameters, context):
            return ToolResult(success=True)

    tool = _Plain()
    tool.execute = AsyncMock(wraps=tool.execute)
    registry = _build_registry([tool])
    runner = CommandRunner(registry=registry, resolver=resolver)
    result = await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="plain",
        arguments={},
        invocation_text="/plain",
    )
    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    # Only a result row gets written for an upfront rejection.
    assert len(_stub_chat_store) == 1
    assert _stub_chat_store[0].message_kind == "command_result"

    tool.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_missing", [False, True])
async def test_unknown_tool_obeys_invocability_preflight(_stub_chat_store, tmp_path, allow_missing):
    path = tmp_path / "allow.toml"
    path.write_text('allow = ["ghost"]' if allow_missing else "allow = []")
    registry = _build_registry([])
    registry.execute = AsyncMock()
    gateway = SimpleNamespace(gate=AsyncMock())
    runner = CommandRunner(
        registry=registry,
        resolver=UserInvocableResolver(whitelist_path=path),
        permission_gateway_provider=lambda: gateway,
    )
    result = await runner.run_tool_command(
        user_id="u1", session_id="s1", tool_name="ghost", arguments={}, invocation_text="/ghost"
    )
    assert result.success is False
    assert result.error_code == (
        ToolErrorCode.TOOL_NOT_FOUND.value
        if allow_missing
        else ToolErrorCode.PERMISSION_DENIED.value
    )
    registry.execute.assert_not_awaited()
    gateway.gate.assert_not_awaited()
    assert [row.message_kind for row in _stub_chat_store] == ["command_result"]


@pytest.mark.asyncio
async def test_dangerous_tool_refused_when_gateway_missing(_stub_chat_store, resolver):
    """Fail-closed: without a permission gateway, dangerous tools are refused
    and their `execute` is never called."""
    dangerous = _DangerousTool()
    execute_spy = AsyncMock(side_effect=dangerous.execute)
    dangerous.execute = execute_spy  # type: ignore[assignment]
    registry = _build_registry([dangerous])

    runner = CommandRunner(
        registry=registry,
        resolver=resolver,
        permission_gateway_provider=None,
    )
    result = await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="rm",
        arguments={},
        invocation_text="/rm",
    )
    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    execute_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_dangerous_tool_is_refused_when_gateway_missing(
    _stub_chat_store, resolver
):
    """All command tools fail closed when the gateway is absent."""
    captured_ctx: list = []
    echo = _EchoTool()
    original_execute = echo.execute

    async def spy_execute(parameters, context):
        captured_ctx.append(context)
        return await original_execute(parameters, context)

    echo.execute = spy_execute  # type: ignore[assignment]
    registry = _build_registry([echo])

    runner = CommandRunner(
        registry=registry,
        resolver=resolver,
        permission_gateway_provider=None,
    )
    result = await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="echo",
        arguments={"text": "hi"},
        invocation_text="/echo text=hi",
    )
    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    assert captured_ctx == []


@pytest.mark.asyncio
async def test_dangerous_tool_blocked_by_gateway(_stub_chat_store, resolver):
    """Dangerous tool, gateway denies → result is a permission_denied row."""
    tool = _DangerousTool()
    tool.execute = AsyncMock(wraps=tool.execute)
    registry = _build_registry([tool])
    requests = []

    class _DenyingGateway:
        async def gate(self, **kwargs):
            requests.append(kwargs)
            from magi.control.permission.contracts import (
                PermissionDecision,
                PermissionOutcome,
            )

            return PermissionDecision(
                request_id="req_1",
                outcome=PermissionOutcome.DENIED,
                source="rule",
                reason="manual deny",
            )

    runner = CommandRunner(
        registry=registry,
        resolver=resolver,
        permission_gateway_provider=lambda: _DenyingGateway(),
    )
    result = await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="rm",
        arguments={"path": "important.txt"},
        invocation_text="/rm",
        workspace="/workspace",
        agent_id="agent-command",
    )
    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    # invocation row still written (we attempted), then a result row with
    # the denial.
    assert _stub_chat_store[0].message_kind == "command_invocation"
    assert _stub_chat_store[1].message_kind == "command_result"
    assert "manual deny" in _stub_chat_store[1].content_text

    from magi.control.permission.contracts import ToolOrigin

    tool.execute.assert_not_awaited()
    assert requests == [
        dict(
            tool_name="rm",
            arguments={"path": "important.txt"},
            agent_id="agent-command",
            origin=ToolOrigin.CHAT,
            session_id="s1",
            turn_id=_stub_chat_store[0].turn_id,
            workspace="/workspace",
            tool_is_dangerous=True,
            tool_risk_level=None,
            tool_risk_authoritative=False,
        )
    ]


@pytest.mark.asyncio
async def test_dangerous_tool_allowed_by_gateway_runs(_stub_chat_store, resolver):
    registry = _build_registry([_DangerousTool()])

    runner = CommandRunner(
        registry=registry,
        resolver=resolver,
        permission_gateway_provider=lambda: _AllowingGateway(),
    )
    result = await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="rm",
        arguments={},
        invocation_text="/rm",
    )
    assert result.success is True
    assert result.output_text == "wiped"
