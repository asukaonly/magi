from __future__ import annotations

from typing import Any

import pytest

from magi.agent.execution.function_calling.orchestrator import FunctionCallingOrchestrator
from magi.agent.execution.function_calling.step_models import FunctionCallingStepState
from magi.llm.model_context import ModelContextProfile


class _ToolRegistry:
    def __init__(self, descriptions: dict[str, str]) -> None:
        self._descriptions = descriptions
        self._skills: dict[str, Any] = {}

    def list_tools(self, category: str | None = None) -> list[str]:
        if category == "control":
            return []
        return list(self._descriptions)

    def get_tool_info(self, name: str) -> dict[str, Any] | None:
        description = self._descriptions.get(name)
        if description is None:
            return None
        return {
            "name": name,
            "description": description,
            "parameters": [],
        }

    def is_skill(self, name: str) -> bool:
        return False


def _orchestrator(
    descriptions: dict[str, str],
    *,
    context_window: int,
    max_output_tokens: int,
) -> FunctionCallingOrchestrator:
    orchestrator = FunctionCallingOrchestrator(_ToolRegistry(descriptions))
    orchestrator._active_model_context = ModelContextProfile(
        provider_id="test",
        model_id="test-model",
        context_window=context_window,
        max_output_tokens=max_output_tokens,
    )
    return orchestrator


@pytest.mark.asyncio
async def test_prepare_context_fails_when_fixed_prompt_still_exceeds_capacity() -> None:
    orchestrator = _orchestrator({}, context_window=1_000, max_output_tokens=100)
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": "keep this current request"}],
        effective_system_prompt="s" * 5_000,
        tools=[],
    )

    failure = await orchestrator._prepare_context_for_model(state)

    assert failure is not None
    assert failure.status == "failed"
    assert failure.failure_reason == "Context window exceeded"
    assert state.messages[-1]["content"] == "keep this current request"


@pytest.mark.asyncio
async def test_prepare_context_drops_lower_priority_optional_tools_until_fit() -> None:
    descriptions = {
        "primary": "p" * 4_000,
        "secondary": "s" * 4_000,
        "find-relevant-tools": "Discover another tool when needed.",
    }
    orchestrator = _orchestrator(
        descriptions,
        context_window=2_000,
        max_output_tokens=200,
    )
    selected = ["primary", "secondary", "find-relevant-tools"]
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": "use the primary capability"}],
        effective_system_prompt="system",
        tools=orchestrator._build_tools_parameter(selected),
        selected_tool_names=list(selected),
    )

    failure = await orchestrator._prepare_context_for_model(state)

    assert failure is None
    assert state.selected_tool_names == ["primary", "find-relevant-tools"]
    assert [tool["function"]["name"] for tool in state.tools] == [
        "find-relevant-tools",
        "primary",
    ]


@pytest.mark.asyncio
async def test_prepare_context_keeps_tool_set_above_trigger_when_capacity_allows() -> None:
    descriptions = {
        "primary": "p" * 500,
        "secondary": "s" * 500,
        "find-relevant-tools": "Discover another tool when needed.",
    }
    orchestrator = _orchestrator(
        descriptions,
        context_window=4_000,
        max_output_tokens=400,
    )
    selected = ["primary", "secondary", "find-relevant-tools"]
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": "keep the cached tool set"}],
        effective_system_prompt="system " * 1_500,
        tools=orchestrator._build_tools_parameter(selected),
        selected_tool_names=list(selected),
    )
    before = orchestrator._measure_context_usage(state)

    failure = await orchestrator._prepare_context_for_model(state)

    assert before.requires_compaction is True
    assert before.fits_input_capacity is True
    assert failure is None
    assert state.selected_tool_names == selected


@pytest.mark.asyncio
async def test_prepare_context_never_drops_only_capability_tool() -> None:
    descriptions = {
        "primary": "p" * 5_000,
        "find-relevant-tools": "Discover another tool when needed.",
    }
    orchestrator = _orchestrator(
        descriptions,
        context_window=1_000,
        max_output_tokens=100,
    )
    selected = ["primary", "find-relevant-tools"]
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": "use the primary capability"}],
        effective_system_prompt="system",
        tools=orchestrator._build_tools_parameter(selected),
        selected_tool_names=list(selected),
    )

    failure = await orchestrator._prepare_context_for_model(state)

    assert failure is not None
    assert state.selected_tool_names == selected
