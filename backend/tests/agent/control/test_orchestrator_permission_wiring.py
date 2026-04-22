"""Integration tests — PermissionGateway wired into FunctionCallingOrchestrator."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.agent.control.common import InteractionBroker
from magi.agent.control.permission.classifier import RiskClassifier
from magi.agent.control.permission.gateway import (
    PermissionGateway,
    UserPromptResponse,
)
from magi.agent.control.permission.rules import PermissionRuleStore
from magi.agent.control.settings import ControlSettings, PermissionMode
from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
    ToolCall,
)
from magi.tools.schema import ToolErrorCode, ToolResult


class _FakeToolRegistry:
    """Minimal registry that records executions and lets tests pre-flag ``dangerous``."""

    def __init__(self, *, dangerous: bool = False) -> None:
        self._dangerous = dangerous
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def is_skill(self, _tool_name: str) -> bool:
        return False

    def get_tool_info(self, _tool_name: str) -> dict[str, Any]:
        return {"dangerous": self._dangerous}

    async def execute(self, tool_name: str, arguments: dict, _context) -> ToolResult:
        self.executed.append((tool_name, arguments))
        return ToolResult(success=True, data="ok")


async def _make_gateway(
    *,
    mode: PermissionMode,
    prompter: Any = None,
) -> PermissionGateway:
    rules = PermissionRuleStore(db_path=None)
    await rules.initialize()
    return PermissionGateway(
        classifier=RiskClassifier(),
        rules=rules,
        broker=InteractionBroker(),
        settings_provider=lambda: ControlSettings(permission_mode=mode),
        prompter=prompter,
        prompt_timeout_seconds=1.0,
    )


def _orchestrator(
    *, registry: _FakeToolRegistry, gateway: PermissionGateway | None
) -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        tool_registry=registry,
        llm_adapter=SimpleNamespace(model_name="fake", provider_name="fake"),
        permission_gateway=gateway,
    )


@pytest.mark.asyncio
async def test_gateway_allows_low_risk_and_registry_runs() -> None:
    registry = _FakeToolRegistry()
    gateway = await _make_gateway(mode=PermissionMode.HIGH_ONLY)
    orch = _orchestrator(registry=registry, gateway=gateway)

    result = await orch._execute_tool_call(
        tool_call=ToolCall(id="c1", name="bash", arguments={"command": "ls -la"}),
        user_id="u",
        session_id="s",
        turn_id="t",
        intent="chat",
        execution_agent_id="a",
        execution_workspace=None,
        orchestration_strategy=None,
    )

    assert result.success is True
    assert registry.executed == [("bash", {"command": "ls -la"})]


@pytest.mark.asyncio
async def test_gateway_blocks_kill_listed_and_returns_tool_error() -> None:
    registry = _FakeToolRegistry()
    gateway = await _make_gateway(mode=PermissionMode.OFF)
    orch = _orchestrator(registry=registry, gateway=gateway)

    result = await orch._execute_tool_call(
        tool_call=ToolCall(id="c1", name="bash", arguments={"command": "rm -rf /"}),
        user_id="u",
        session_id=None,
        turn_id=None,
        intent="chat",
        execution_agent_id="a",
        execution_workspace=None,
        orchestration_strategy=None,
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    assert "safety fuse" in (result.error or "")
    assert registry.executed == []


@pytest.mark.asyncio
async def test_gateway_user_denial_surfaces_reason_to_llm() -> None:
    class _Deny:
        async def __call__(self, request, *, timeout_seconds):
            return UserPromptResponse(allow=False, note="not now")

    registry = _FakeToolRegistry()
    gateway = await _make_gateway(mode=PermissionMode.HIGH_ONLY, prompter=_Deny())
    orch = _orchestrator(registry=registry, gateway=gateway)

    result = await orch._execute_tool_call(
        tool_call=ToolCall(
            id="c1", name="bash", arguments={"command": "npm install react"}
        ),
        user_id="u",
        session_id="s",
        turn_id="t",
        intent="chat",
        execution_agent_id="a",
        execution_workspace=None,
        orchestration_strategy=None,
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    assert "not now" in (result.error or "")
    assert registry.executed == []


@pytest.mark.asyncio
async def test_gateway_off_mode_passes_dangerous_npm_install() -> None:
    registry = _FakeToolRegistry()
    gateway = await _make_gateway(mode=PermissionMode.OFF)
    orch = _orchestrator(registry=registry, gateway=gateway)

    result = await orch._execute_tool_call(
        tool_call=ToolCall(
            id="c1", name="bash", arguments={"command": "npm install react"}
        ),
        user_id="u",
        session_id=None,
        turn_id=None,
        intent="chat",
        execution_agent_id="a",
        execution_workspace=None,
        orchestration_strategy=None,
    )

    assert result.success is True
    assert registry.executed == [("bash", {"command": "npm install react"})]


@pytest.mark.asyncio
async def test_worker_intent_tags_origin_as_subagent() -> None:
    captured: list = []

    class _Capture:
        async def __call__(self, request, *, timeout_seconds):
            captured.append(request)
            return UserPromptResponse(allow=True)

    registry = _FakeToolRegistry()
    gateway = await _make_gateway(
        mode=PermissionMode.HIGH_ONLY, prompter=_Capture()
    )
    orch = _orchestrator(registry=registry, gateway=gateway)

    await orch._execute_tool_call(
        tool_call=ToolCall(
            id="c1", name="bash", arguments={"command": "npm install x"}
        ),
        user_id="u",
        session_id="s",
        turn_id="t",
        intent="worker_explore",
        execution_agent_id="a",
        execution_workspace=None,
        orchestration_strategy=None,
    )

    from magi.agent.control.permission import ToolOrigin

    assert captured and captured[0].origin is ToolOrigin.SUBAGENT


@pytest.mark.asyncio
async def test_orchestrator_without_gateway_behaves_as_before() -> None:
    registry = _FakeToolRegistry(dangerous=True)
    orch = _orchestrator(registry=registry, gateway=None)

    result = await orch._execute_tool_call(
        tool_call=ToolCall(id="c1", name="bash", arguments={"command": "rm -rf /"}),
        user_id="u",
        session_id=None,
        turn_id=None,
        intent="chat",
        execution_agent_id="a",
        execution_workspace=None,
        orchestration_strategy=None,
    )

    # Gateway off → the registry ran (dev hasn't opted in yet).
    assert result.success is True
    assert registry.executed == [("bash", {"command": "rm -rf /"})]
