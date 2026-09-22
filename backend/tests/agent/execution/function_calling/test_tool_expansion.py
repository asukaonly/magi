from __future__ import annotations

from types import SimpleNamespace

from magi.agent.execution.function_calling.step_models import FunctionCallingStepState
from magi.agent.execution.function_calling.tool_expansion import (
    apply_tool_expansion_from_results,
)


class _Registry:
    _KNOWN_TOOLS = {"file_write", "verify", "weather"}

    def get_tool_info(self, name: str):  # type: ignore[no-untyped-def]
        if name not in self._KNOWN_TOOLS and not name.startswith("resident_"):
            return None
        return {"name": name, "description": name, "parameters": []}

    def is_skill(self, name: str) -> bool:
        return False

    def get_tool(self, name: str):  # type: ignore[no-untyped-def]
        effect_class = "local_write" if name == "file_write" else "read_only"
        replay_policy = "unknown" if name == "file_write" else "read_only"
        schema = SimpleNamespace(
            name=name,
            effect_class=effect_class,
            effect_replay_policy=replay_policy,
            dangerous=False,
            requires_auth=False,
            metadata={},
        )
        return SimpleNamespace(get_schema=lambda: schema)


def _host() -> SimpleNamespace:
    from magi.agent.execution.function_calling.orchestrator import FunctionCallingOrchestrator

    registry = _Registry()
    return SimpleNamespace(
        _MAX_TOOL_EXPANSIONS_PER_TURN=FunctionCallingOrchestrator._MAX_TOOL_EXPANSIONS_PER_TURN,
        _MAX_TOOLS_PER_EXPANSION=2,
        tool_registry=registry,
        _build_tools_parameter=lambda names: [
            {"type": "function", "function": {"name": name}} for name in names
        ],
    )


def _result(*names: str) -> SimpleNamespace:
    return SimpleNamespace(
        success=True,
        data={"tool_expansion": {"append_tools": list(names)}},
    )


def test_expansion_budget_is_relative_to_the_initial_surface() -> None:
    selected = [f"resident_{index}" for index in range(11)]
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="",
        tools=[],
        selected_tool_names=list(selected),
    )

    additions = apply_tool_expansion_from_results(
        _host(),
        state=state,
        tool_results=[_result("weather")],
    )

    assert additions == ["weather"]
    assert state.selected_tool_names == [*selected, "weather"]


def test_local_write_discovery_reserves_a_validation_companion() -> None:
    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="",
        tools=[],
        selected_tool_names=["resident_0"],
    )

    additions = apply_tool_expansion_from_results(
        _host(),
        state=state,
        tool_results=[_result("weather", "file_write")],
    )

    assert additions == ["file_write", "verify"]
    assert state.selected_tool_names == ["resident_0", "file_write", "verify"]


def test_sequential_discovery_keeps_prior_tools_and_stops_at_the_run_budget() -> None:
    host = _host()
    state = FunctionCallingStepState(messages=[], effective_system_prompt="", tools=[])
    for name in ("weather", "file_write", "resident_1"):
        assert name in apply_tool_expansion_from_results(
            host, state=state, tool_results=[_result(name)]
        )
    selected = list(state.selected_tool_names)
    assert "verify" in selected
    assert (
        apply_tool_expansion_from_results(host, state=state, tool_results=[_result("resident_2")])
        == []
    )
    assert state.selected_tool_names == selected
    assert "budget is exhausted" in state.messages[-1]["content"]


def test_expansion_rejects_over_model_limit_without_losing_existing_tools() -> None:
    host = _host()
    host._active_model_context = SimpleNamespace(max_tool_schemas=1)
    state = FunctionCallingStepState(messages=[], effective_system_prompt="", tools=[])
    assert apply_tool_expansion_from_results(
        host, state=state, tool_results=[_result("weather")]
    ) == ["weather"]
    assert (
        apply_tool_expansion_from_results(host, state=state, tool_results=[_result("file_write")])
        == []
    )
    assert state.selected_tool_names == ["weather"]
    assert state.tool_expansion_count == 1
    assert "tool_schema_limit_exceeded" in state.messages[-1]["content"]


def test_expansion_respects_explicit_run_schema_token_limit() -> None:
    from magi.agent.execution.model_capabilities import ModelCapabilityProfile

    state = FunctionCallingStepState(
        messages=[],
        effective_system_prompt="",
        tools=[],
        model_capabilities=ModelCapabilityProfile(max_schema_tokens=1),
    )
    assert (
        apply_tool_expansion_from_results(_host(), state=state, tool_results=[_result("weather")])
        == []
    )
    assert state.tools == []
    assert state.tool_expansion_count == 0
    assert "tool_schema_token_limit_exceeded" in state.messages[-1]["content"]
