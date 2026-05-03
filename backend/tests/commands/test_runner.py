"""Tests for CommandRunner."""

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

from magi.commands import resolver as resolver_mod
from magi.commands.runner import CommandRunner
from magi.commands.resolver import UserInvocableResolver


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

    class _FakeStore:
        async def append_message(self, record, **kwargs):
            appended.append(record)

    fake = _FakeStore()
    from magi.commands import runner as runner_mod
    monkeypatch.setattr(runner_mod, "get_chat_store", lambda: fake)
    yield appended


@pytest.fixture
def resolver(tmp_path):
    return UserInvocableResolver(whitelist_path=tmp_path / "missing.toml")


@pytest.mark.asyncio
async def test_writes_invocation_then_result(_stub_chat_store, resolver):
    registry = _build_registry([_EchoTool()])
    runner = CommandRunner(registry=registry, resolver=resolver)
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

    registry = _build_registry([_Plain()])
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


@pytest.mark.asyncio
async def test_unknown_tool_returns_not_found(_stub_chat_store, resolver):
    registry = _build_registry([])
    runner = CommandRunner(registry=registry, resolver=resolver)
    result = await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="ghost",
        arguments={},
        invocation_text="/ghost",
    )
    assert result.success is False
    # ghost isn't user_invocable either; permission_denied wins.
    assert result.error_code in (
        ToolErrorCode.TOOL_NOT_FOUND.value,
        ToolErrorCode.PERMISSION_DENIED.value,
    )


@pytest.mark.asyncio
async def test_dangerous_tool_blocked_by_gateway(_stub_chat_store, resolver):
    """Dangerous tool, gateway denies → result is a permission_denied row."""
    registry = _build_registry([_DangerousTool()])

    class _DenyingGateway:
        async def gate(self, **kwargs):
            from magi.agent.control.permission.contracts import (
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
        arguments={},
        invocation_text="/rm",
    )
    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    # invocation row still written (we attempted), then a result row with
    # the denial.
    assert _stub_chat_store[0].message_kind == "command_invocation"
    assert _stub_chat_store[1].message_kind == "command_result"
    assert "manual deny" in _stub_chat_store[1].content_text


@pytest.mark.asyncio
async def test_dangerous_tool_allowed_by_gateway_runs(_stub_chat_store, resolver):
    registry = _build_registry([_DangerousTool()])

    class _AllowingGateway:
        async def gate(self, **kwargs):
            from magi.agent.control.permission.contracts import (
                PermissionDecision,
                PermissionOutcome,
            )

            return PermissionDecision(
                request_id="req_2",
                outcome=PermissionOutcome.ALLOWED,
                source="rule",
                reason="ok",
            )

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


@pytest.mark.asyncio
async def test_notifier_invoked_for_each_message(_stub_chat_store, resolver):
    registry = _build_registry([_EchoTool()])
    seen: list[tuple[str, str, str]] = []

    async def notifier(user_id, session_id, message_id):
        seen.append((user_id, session_id, message_id))

    runner = CommandRunner(registry=registry, resolver=resolver, notifier=notifier)
    await runner.run_tool_command(
        user_id="u1",
        session_id="s1",
        tool_name="echo",
        arguments={"text": "hi"},
        invocation_text="/echo text=hi",
    )
    assert len(seen) == 2
