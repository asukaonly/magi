"""Universal runtime-fact admission across unified agent drivers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.config.models import ThinkingDepth
from magi.context.prompt_lifecycle import DEFAULT_HEADLESS_SYSTEM_PROMPT
from magi.control.run_control import null_run_control
from magi.utils.model_context_messages import is_working_context_message
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


@pytest.mark.asyncio
async def test_attachment_grounding_keeps_instruction_out_of_stable_system_prompt() -> None:
    recorded_call: dict[str, object] = {}

    class _GroundingHost(_Host):
        _current_messages: list[dict[str, object]] = []

        async def _call_llm_without_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            recorded_call.update(kwargs)
            return {
                "content": (
                    '{"summary":"diagram","visible_facts":[],"uncertainty":[],'
                    '"attachment_refs":[]}'
                )
            }

        @staticmethod
        def _format_exception_trace_text(exc: Exception) -> str:
            return str(exc)

    class _Journal:
        async def record_effective_context(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            _ = (args, kwargs)

    state = FunctionCallingStepState(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {"type": "image", "data": "data:image/png;base64,AA=="},
                ],
            }
        ],
        effective_system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
        tools=[],
    )
    flow = FunctionCallingModelCapabilityFlow(_GroundingHost(), _Journal())

    outcome = await flow._ground_attachments(
        state=state,
        run_input=_request(supports_tool_calls=False),
        control=null_run_control(),
        thinking_depth=ThinkingDepth.LOW,
    )

    assert outcome is None
    assert recorded_call["system_prompt"] == DEFAULT_HEADLESS_SYSTEM_PROMPT
    grounding_messages = recorded_call["messages"]
    assert isinstance(grounding_messages, list)
    assert is_working_context_message(grounding_messages[-1])
    assert "Attachment grounding step" in str(grounding_messages[-1]["content"])
    assert "Attachment grounding step" not in DEFAULT_HEADLESS_SYSTEM_PROMPT
