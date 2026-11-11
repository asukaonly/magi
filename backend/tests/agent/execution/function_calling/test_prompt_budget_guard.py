from __future__ import annotations

import json
from typing import Any

import pytest

from magi.agent.execution.function_calling.orchestrator import FunctionCallingOrchestrator
from magi.agent.execution.function_calling.step_models import FunctionCallingStepState
from magi.llm.model_context import ModelContextProfile
from magi.llm.model_context import ResolvedModel


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
async def test_prepare_context_never_truncates_oversized_current_request() -> None:
    orchestrator = _orchestrator({}, context_window=1_000, max_output_tokens=100)
    current_request = "critical request " + "x" * 5_000
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": current_request}],
        effective_system_prompt="system",
        tools=[],
    )

    failure = await orchestrator._prepare_context_for_model(state)

    assert failure is not None
    assert failure.failure_reason == "Context window exceeded"
    assert state.messages[-1]["content"] == current_request


@pytest.mark.asyncio
async def test_prepare_context_counts_inline_image_as_media_not_encoded_text() -> None:
    orchestrator = _orchestrator({}, context_window=128_000, max_output_tokens=8_192)
    image_data = "A" * 600_000
    state = FunctionCallingStepState(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image."},
                    {
                        "type": "image",
                        "mime_type": "image/png",
                        "data": image_data,
                    },
                ],
            }
        ],
        effective_system_prompt="system",
        tools=[],
    )

    failure = await orchestrator._prepare_context_for_model(state)

    assert failure is None
    assert state.messages[0]["content"][1]["data"] == image_data


@pytest.mark.asyncio
async def test_prepare_context_compacts_tool_payload_without_breaking_protocol() -> None:
    orchestrator = _orchestrator({}, context_window=40_000, max_output_tokens=4_000)
    current_request = "analyze the tool result"
    tool_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "demo", "arguments": "{}"},
            }
        ],
    }
    state = FunctionCallingStepState(
        messages=[
            {"role": "user", "content": current_request},
            tool_call,
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": json.dumps(
                    {
                        "success": True,
                        "data": {"rows": ["x" * 2_000 for _ in range(60)]},
                        "error": None,
                        "error_code": None,
                    }
                ),
            },
        ],
        effective_system_prompt="system",
        tools=[],
    )

    failure = await orchestrator._prepare_context_for_model(state)

    assert failure is None
    assert state.messages[0]["content"] == current_request
    assert state.messages[1] == tool_call
    assert state.messages[2]["tool_call_id"] == "call-1"
    compacted_payload = json.loads(state.messages[2]["content"])
    assert compacted_payload["success"] is True
    assert compacted_payload["data"]["__context_truncated__"] is True


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
    assert state.selected_tool_names == ["primary", "find-relevant-tools"]


@pytest.mark.asyncio
async def test_final_response_budget_ignores_tools_not_sent_to_provider() -> None:
    descriptions = {"large-tool": "x" * 20_000}
    orchestrator = _orchestrator(
        descriptions,
        context_window=4_000,
        max_output_tokens=400,
    )
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": "write the final answer"}],
        effective_system_prompt="system",
        tools=orchestrator._build_tools_parameter(["large-tool"]),
        selected_tool_names=["large-tool"],
    )

    with_tools = orchestrator._measure_context_usage(state)
    without_tools = orchestrator._measure_context_usage(state, include_tools=False)
    failure = await orchestrator._prepare_context_for_model(
        state,
        include_tools=False,
    )

    assert with_tools.fits_input_capacity is False
    assert without_tools.fits_input_capacity is True
    assert failure is None
    assert state.selected_tool_names == ["large-tool"]


@pytest.mark.asyncio
async def test_model_switch_takes_effect_next_run_after_capacity_guard(monkeypatch) -> None:
    from types import SimpleNamespace

    from magi.agent.execution.function_calling.run_input import AgentRunRequest
    from magi.agent.turn_input import UserTurnInput
    from magi.context.prompt_lifecycle import DEFAULT_HEADLESS_SYSTEM_PROMPT
    from magi.llm.provider_bridge import LLMProviderBridge, ProviderResponse

    large = ResolvedModel(
        SimpleNamespace(model_name="large", provider_name="test"),
        ModelContextProfile("test", "large", 128_000, 8_192),
    )
    small = ResolvedModel(
        SimpleNamespace(model_name="small", provider_name="test"),
        ModelContextProfile("test", "small", 4_000, 1_024),
    )
    selected = large
    host = FunctionCallingOrchestrator(_ToolRegistry({}), active_model_provider=lambda: selected)
    prepare_context = host._prepare_context_for_model
    provider_models = []

    async def switch_after_guard(state, **kwargs):
        nonlocal selected
        failure = await prepare_context(state, **kwargs)
        selected = small
        return failure

    async def chat_with_tools(bridge, **kwargs):
        provider_models.append(bridge.llm.model_name)
        return ProviderResponse(content="complete")

    monkeypatch.setattr(host, "_prepare_context_for_model", switch_after_guard)
    monkeypatch.setattr(LLMProviderBridge, "chat_with_tools", chat_with_tools)
    for prompt in ("x" * 20_000, "short next request"):
        outcome = await host.run(AgentRunRequest(
            turn=UserTurnInput(text=prompt), system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
            selected_tools=[], user_id="test",
        ))
        assert outcome.status == "completed"

    assert provider_models == ["large", "small"]


@pytest.mark.asyncio
async def test_concurrent_runs_keep_their_guarded_model_and_compactor(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from magi.agent.execution.function_calling.run_input import AgentRunRequest
    from magi.agent.turn_input import UserTurnInput
    from magi.context.prompt_lifecycle import DEFAULT_HEADLESS_SYSTEM_PROMPT
    from magi.llm.provider_bridge import LLMProviderBridge, ProviderResponse

    large = ResolvedModel(
        SimpleNamespace(model_name="large", provider_name="test"),
        ModelContextProfile("test", "large", 128_000, 8_192),
    )
    small = ResolvedModel(
        SimpleNamespace(model_name="small", provider_name="test"),
        ModelContextProfile("test", "small", 4_000, 1_024),
    )
    selected = large
    host = FunctionCallingOrchestrator(_ToolRegistry({}), active_model_provider=lambda: selected)
    large_guarded, resume_large = asyncio.Event(), asyncio.Event()
    prepare_context = host._prepare_context_for_model
    compactors, provider_models = {}, []

    async def guard(state, **kwargs):
        model_id = host._active_model_context.model_id
        failure = await prepare_context(state, **kwargs)
        assert failure is None
        compactors[model_id] = host._context_compactor
        if model_id == "large":
            host._context_compactor.record_input_tokens(10_000)
            large_guarded.set()
            await resume_large.wait()
            assert host._active_model_context == large.context
            assert host._context_compactor.get_usage()["used_tokens"] == 10_000
        else:
            assert host._context_compactor.get_usage() is None
            host._context_compactor.record_input_tokens(1_000)
        return failure

    async def chat_with_tools(bridge, **kwargs):
        provider_models.append(bridge.llm.model_name)
        return ProviderResponse(content="complete")

    def request(text):
        return AgentRunRequest(
            turn=UserTurnInput(text=text), system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
            selected_tools=[], user_id="test",
        )

    monkeypatch.setattr(host, "_prepare_context_for_model", guard)
    monkeypatch.setattr(LLMProviderBridge, "chat_with_tools", chat_with_tools)
    large_run = asyncio.create_task(host.run(request("x" * 20_000)))
    await asyncio.wait_for(large_guarded.wait(), timeout=5)
    try:
        selected = small
        small_outcome = await host.run(request("short concurrent request"))
    finally:
        resume_large.set()
    large_outcome = await large_run

    assert small_outcome.status == large_outcome.status == "completed"
    assert provider_models == ["small", "large"]
    assert compactors["small"] is not compactors["large"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_run_model_scope_restores_after_failure_or_cancellation(monkeypatch, cancelled) -> None:
    import asyncio
    from types import SimpleNamespace

    from magi.agent.execution.function_calling.run_input import AgentRunRequest
    from magi.agent.turn_input import UserTurnInput
    from magi.context.prompt_lifecycle import DEFAULT_HEADLESS_SYSTEM_PROMPT

    selected = ResolvedModel(
        SimpleNamespace(model_name="selected", provider_name="test"),
        ModelContextProfile("test", "selected", 32_000, 4_000),
    )
    host = FunctionCallingOrchestrator(_ToolRegistry({}), active_model_provider=lambda: selected)
    initial_compactor, initial_context = host._context_compactor, host._active_model_context
    error = asyncio.CancelledError if cancelled else RuntimeError

    async def interrupted_run(*args, **kwargs):
        host._resolve_llm()
        assert host.llm is selected.adapter
        assert host._context_compactor is not initial_compactor
        raise error("interrupted")

    monkeypatch.setattr(host._loop_runner, "run", interrupted_run)
    with pytest.raises(error):
        await host.run(AgentRunRequest(
            turn=UserTurnInput(text="request"), system_prompt=DEFAULT_HEADLESS_SYSTEM_PROMPT,
            selected_tools=[], user_id="test",
        ))
    assert host.llm is None
    assert host.provider_bridge is None
    assert host._active_model_context == initial_context
    assert host._context_compactor is initial_compactor
