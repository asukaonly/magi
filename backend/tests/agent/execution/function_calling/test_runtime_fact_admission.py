"""Universal runtime-fact admission across unified agent drivers."""

from __future__ import annotations

from types import SimpleNamespace

from magi.agent.execution.function_calling.model_capability_flow import (
    FunctionCallingModelCapabilityFlow,
)
from magi.agent.execution.function_calling.run_input import AgentRunRequest
from magi.agent.execution.function_calling.step_models import FunctionCallingStepState
from magi.agent.execution.model_capabilities import ModelCapabilityProfile
from magi.agent.turn_input import UserTurnInput


class _Registry:
    def list_tools(self) -> list[str]:
        return ["current_time", "inspect"]


class _Host:
    tool_registry = _Registry()

    @staticmethod
    def _build_tools_parameter(selected_tools: list[str]) -> list[dict[str, object]]:
        return [{"name": name} for name in selected_tools]


def _request(*, supports_tool_calls: bool) -> AgentRunRequest:
    return AgentRunRequest.headless(
        turn=UserTurnInput(text="report the current time"),
        selected_tools=[],
        user_id="user-1",
        model_context_port=None,
        model_capabilities=ModelCapabilityProfile(
            supports_tool_calls=supports_tool_calls
        ),
    )


def test_runtime_fact_is_admitted_for_tool_capable_headless_run() -> None:
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": "report the current time"}],
        effective_system_prompt="stable",
        tools=[],
    )
    flow = FunctionCallingModelCapabilityFlow(_Host(), SimpleNamespace())

    flow.admit_runtime_facts(state=state, run_input=_request(supports_tool_calls=True))

    assert state.selected_tool_names == ["current_time"]
    assert state.tools == [{"name": "current_time"}]


def test_runtime_fact_is_not_admitted_when_model_cannot_call_tools() -> None:
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": "report the current time"}],
        effective_system_prompt="stable",
        tools=[],
    )
    flow = FunctionCallingModelCapabilityFlow(_Host(), SimpleNamespace())

    flow.admit_runtime_facts(state=state, run_input=_request(supports_tool_calls=False))

    assert state.selected_tool_names == []
    assert state.tools == []
