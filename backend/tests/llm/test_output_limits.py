"""Output capacity, request omission, and truncation at the provider boundary."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from magi.config.models import ThinkingDepth
from magi.llm.anthropic import AnthropicAdapter
from magi.llm.openai import OpenAIAdapter
from magi.llm.model_context import ModelContextProfile
from magi.llm.output_limit import OutputLimitReached
from magi.llm.provider_bridge import LLMProviderBridge


async def stream(items):
    for item in items:
        yield item


def bridge_for(provider, result):
    adapter = (AnthropicAdapter if provider == "anthropic" else OpenAIAdapter).__new__(
        AnthropicAdapter if provider == "anthropic" else OpenAIAdapter
    )
    adapter._model = "claude-sonnet-4-6" if provider == "anthropic" else "deepseek-flash"
    adapter._provider = provider
    adapter._provider_plan = adapter._provider_instance_id = adapter._base_url = None
    adapter.model_context = ModelContextProfile(provider, adapter._model, 1_000_000, 384_000)
    create = AsyncMock(return_value=result)
    adapter._client = NS(messages=NS(create=create), chat=NS(completions=NS(create=create)))
    bridge = LLMProviderBridge(adapter)
    bridge._operations._emit_usage_event = AsyncMock()
    return bridge, create


async def invoke(bridge, streaming, tools, **kwargs):
    args = dict(system_prompt="system", messages=[{"role": "user", "content": "hello"}],
                thinking_depth=ThinkingDepth.NONE, **kwargs)
    if tools:
        args["tools"] = [{"type": "function", "function": {"name": "write", "parameters": {"type": "object"}}}]
        if streaming:
            return await bridge.chat_with_tools_stream(**args)
        return await bridge.chat_with_tools(**args)
    if streaming:
        return [event async for event in bridge.chat_response_stream(**args)]
    return await bridge.chat_response(**args)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("tools", [False, True])
async def test_openai_omits_cap_and_rejects_even_parseable_truncated_tools(streaming, tools):
    usage = NS(prompt_tokens=22_533, completion_tokens=4_096, total_tokens=26_629,
               completion_tokens_details=NS(reasoning_tokens=4_096))
    call = NS(index=0, id="call-1", function=NS(name="write", arguments='{"path":"file"}'))
    message = NS(content="partial", tool_calls=[call] if tools else None)
    result = (stream([
        NS(choices=[NS(delta=message, finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None), finish_reason="length")], usage=None),
        NS(choices=[], usage=usage),
    ]) if streaming else NS(choices=[NS(message=message, finish_reason="length")], usage=usage))
    bridge, create = bridge_for("deepseek", result)
    with pytest.raises(OutputLimitReached) as caught:
        await invoke(bridge, streaming, tools)
    assert "max_tokens" not in create.await_args.kwargs
    assert caught.value.token_count("completion_tokens") == 4_096
    recorded = bridge._operations._emit_usage_event.await_args.kwargs
    assert recorded["success"] is False
    assert recorded["usage"].reasoning_tokens == 4_096


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("tools", [False, True])
async def test_anthropic_fills_required_cap_and_retains_truncated_usage(streaming, tools):
    usage = NS(input_tokens=100, output_tokens=4_096, cache_read_input_tokens=20)
    result = (stream([
        NS(type="message_start", message=NS(usage=NS(input_tokens=100, output_tokens=0,
                                                    cache_read_input_tokens=20))),
        NS(type="content_block_delta", delta=NS(type="text_delta", text="partial")),
        NS(type="message_delta", delta=NS(stop_reason="max_tokens"), usage=NS(output_tokens=4_096)),
    ]) if streaming else NS(content=[NS(type="text", text="partial")],
                            stop_reason="max_tokens", usage=usage))
    bridge, create = bridge_for("anthropic", result)
    with pytest.raises(OutputLimitReached) as caught:
        await invoke(bridge, streaming, tools)
    assert create.await_args.kwargs["max_tokens"] == 65_536
    assert caught.value.token_count("prompt_tokens") == 120
    assert caught.value.token_count("completion_tokens") == 4_096
    assert bridge._operations._emit_usage_event.await_args.kwargs["success"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [None, 32_768])
async def test_required_and_explicit_limits_never_exceed_model_capacity(requested):
    bridge, create = bridge_for("anthropic", NS(content=[NS(type="text", text="complete")]))
    bridge.llm.model_context = ModelContextProfile("anthropic", "small", 200_000, 8_000)
    await invoke(bridge, False, False, max_tokens=requested)
    assert create.await_args.kwargs["max_tokens"] == 8_000


@pytest.mark.parametrize("model,capacity,expected", [
    ("gpt-6.1-sol", 384_000, 16_384),
    ("gpt-6.1-sol", 8_000, 8_000),
    ("deepseek-flash", 384_000, 256),
])
def test_short_auxiliary_calls_allow_required_reasoning(model, capacity, expected):
    bridge, _ = bridge_for("openai", None)
    bridge.llm._model = model
    bridge.llm.model_context = ModelContextProfile("openai", model, 1_000_000, capacity)
    options = bridge._operations._apply_provider_options({"max_tokens": 256}, ThinkingDepth.NONE)
    assert options["max_tokens"] == expected
    automatic = bridge._operations._apply_provider_options({"max_tokens": None}, ThinkingDepth.NONE)
    assert "max_tokens" not in automatic


@pytest.mark.parametrize("capacity", [1_000, 8_192])
def test_manual_thinking_leaves_answer_space_within_model_capacity(capacity):
    bridge, _ = bridge_for("anthropic", None)
    bridge.llm._model = "claude-3-7-sonnet-20250219"
    bridge.llm.model_context = ModelContextProfile("anthropic", bridge.llm._model, 200_000, capacity)
    if capacity == 1_000:
        with pytest.raises(ValueError, match="minimum thinking budget"):
            bridge._operations._apply_provider_options({"max_tokens": 4_096}, ThinkingDepth.HIGH)
    else:
        options = bridge._operations._apply_provider_options({"max_tokens": 4_096}, ThinkingDepth.HIGH)
        assert options["max_tokens"] == capacity
        assert options["thinking"]["budget_tokens"] == 4_096


def test_reasoning_floor_keeps_small_context_headroom():
    bridge, _ = bridge_for("openai", None)
    bridge.llm._model = "gpt-6.1-sol"
    bridge.llm.model_context = ModelContextProfile("openai", "gpt-6.1-sol", 8_000, None)
    options = bridge._operations._apply_provider_options({"max_tokens": 256}, ThinkingDepth.NONE)
    assert options["max_tokens"] == 2_000
