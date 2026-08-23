from __future__ import annotations

import importlib
import inspect

import pytest

from magi.agent.task_agents.common import ExecutionMode
from magi.agent.task_agents.handlers.handlers import FunctionCallingHandler
from magi.agent.task_agents.handlers.tool_exposure_policy import ToolExposurePolicy
from magi.tools.context_routing import RouteDecision


def _resolver_module():
    try:
        return importlib.import_module("magi.agent.task_agents.handlers.turn_route_resolver")
    except ModuleNotFoundError as exc:
        pytest.fail(f"turn route resolver module is missing: {exc}")


class _FakeToolRegistry:
    def __init__(self, tools: list[str], *, control_tools: list[str] | None = None) -> None:
        self._tools = list(tools)
        self._control_tools = list(control_tools or [])

    def list_tools(self, category=None):  # type: ignore[no-untyped-def]
        if category == "control":
            return list(self._control_tools)
        return list(self._tools)


def test_turn_route_resolver_exposes_only_discovery_for_discovery_route() -> None:
    module = _resolver_module()
    resolver = module.TurnRouteResolver()

    resolution = resolver.resolve_intent_route(
        user_message="帮我找一个能解析日历的工具",
        route_decision=RouteDecision(
            profile="system",
            graph_shape="reply",
            complexity="simple",
            tool_need="discover",
            tools=[],
            reasoning="needs runtime tool discovery",
        ),
        registered_tools={"find-relevant-tools", "web-search"},
        effective_attachments=[],
        force_direct_external=False,
    )

    assert resolution.execution_mode is ExecutionMode.FUNCTION_CALLING
    assert resolution.selected_tools == ["find-relevant-tools"]
    assert resolution.route_decision.graph_shape == "tool_loop"


def test_turn_route_resolver_builds_execution_tool_surface() -> None:
    module = _resolver_module()
    resolver = module.TurnRouteResolver(
        tool_exposure_policy=ToolExposurePolicy(ttl_seconds=300.0)
    )
    route = RouteDecision(
        profile="chat",
        graph_shape="tool_loop",
        complexity="simple",
        tool_need="direct",
        tools=["weather"],
        needs_orchestration="maybe",
    )
    registry = _FakeToolRegistry(
        ["weather", "todo_write", "find-relevant-tools", "agent"],
        control_tools=["todo_write"],
    )

    selected_tools = resolver.resolve_execution_tools(
        requested_tools=["weather"],
        route_decision=route,
        tool_registry=registry,
        session_key="chat:session-1",
    )

    assert selected_tools == ["weather", "todo_write"]


def test_turn_route_resolver_preserves_explicit_agent_selection() -> None:
    module = _resolver_module()
    resolver = module.TurnRouteResolver(tool_exposure_policy=ToolExposurePolicy())
    route = RouteDecision(
        profile="research",
        graph_shape="tool_loop",
        complexity="medium",
        tool_need="direct",
        tools=["agent"],
        needs_orchestration="maybe",
    )
    registry = _FakeToolRegistry(["agent", "find-relevant-tools"])

    selected_tools = resolver.resolve_execution_tools(
        requested_tools=["agent"],
        route_decision=route,
        tool_registry=registry,
        session_key="chat:session-explicit-agent",
    )

    assert selected_tools == ["agent"]


def test_turn_route_resolver_keeps_local_shell_route_local() -> None:
    module = _resolver_module()
    resolver = module.TurnRouteResolver()

    resolution = resolver.resolve_intent_route(
        user_message="Translate the attached workbook with PowerShell",
        route_decision=RouteDecision(
            profile="coding",
            graph_shape="tool_loop",
            complexity="simple",
            tool_need="direct",
            tools=["powershell"],
            may_write=True,
        ),
        registered_tools={"powershell", "web-search", "find-relevant-tools"},
        effective_attachments=[],
        force_direct_external=False,
    )

    assert resolution.selected_tools == ["powershell"]


def test_turn_route_resolver_adds_web_search_for_direct_external_route() -> None:
    module = _resolver_module()
    resolver = module.TurnRouteResolver()

    resolution = resolver.resolve_intent_route(
        user_message="Check the current external status",
        route_decision=RouteDecision(
            profile="research",
            graph_shape="plan_fanout",
            complexity="medium",
            tool_need="direct",
            tools=["agent"],
            needs_orchestration="required",
        ),
        registered_tools={"agent", "web-search", "find-relevant-tools"},
        effective_attachments=[],
        force_direct_external=True,
    )

    assert resolution.selected_tools == ["web-search"]
    assert resolution.execution_mode is ExecutionMode.FUNCTION_CALLING


def test_function_calling_handler_delegates_execution_tool_routing() -> None:
    source = inspect.getsource(FunctionCallingHandler.build_request)

    assert "resolve_execution_tools" in source
    assert "resolve_resident_system_tools" not in source
    assert "needs_orchestration" not in source
