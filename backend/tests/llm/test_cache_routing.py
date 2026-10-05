"""Provider cache-routing keys (#98).

OpenAI and xAI/Grok auto-cache by prefix but route requests across many backend
nodes; pinning a conversation to one node lifts the cache hit rate. OpenAI takes
a ``prompt_cache_key`` body param, xAI an ``x-grok-conv-id`` header. Both are
keyed on a stable conversation id (magi's ``session_id``) and vendor-gated so
they never reach a provider that would reject them.
"""

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.config.models import ModelVendor
from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import LLMProviderBridge
from magi.llm.provider_bridge.cache_routing import (
    routing_key_from_event_context,
)


# --- pure functions ---


@pytest.mark.parametrize(
    "context,expected",
    [
        (None, None),
        ({}, None),
        ({"session_id": ""}, None),
        ({"session_id": " "}, None),
        ({"session_id": "s1"}, "s1"),
        ({"correlation_id": "c1"}, "c1"),
        ({"session_id": "s1", "correlation_id": "c1"}, "s1"),
    ],
)
def test_cache_route_key_uses_session_then_correlation(context, expected):
    assert routing_key_from_event_context(context) == expected


# --- bridge integration ---


class _OpenAIAdapter(LLMAdapter):
    def __init__(self, client: Any, provider: str = "openai") -> None:
        self._client = client
        self._provider = provider

    async def generate(self, prompt: str, max_tokens: Optional[int] = None,
                       temperature: float = 0.7, **kwargs) -> str:
        return "g"

    async def generate_stream(self, prompt: str, max_tokens: Optional[int] = None,
                              temperature: float = 0.7, **kwargs) -> AsyncIterator[str]:
        if False:
            yield ""

    async def chat(self, messages: List[Dict[str, str]], max_tokens: Optional[int] = None,
                   temperature: float = 0.7, **kwargs) -> str:
        return "c"

    async def chat_stream(self, messages: List[Dict[str, str]], max_tokens: Optional[int] = None,
                          temperature: float = 0.7, **kwargs) -> AsyncIterator[str]:
        if False:
            yield ""

    @property
    def model_name(self) -> str:
        return "gpt-5.2"

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def base_url(self) -> Optional[str]:
        return None


class _RecordingCompletions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: Dict[str, Any] = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _openai_response() -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]),
                                 finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


def _bridge(vendor: ModelVendor) -> tuple[LLMProviderBridge, _RecordingCompletions]:
    completions = _RecordingCompletions(_openai_response())
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    bridge = LLMProviderBridge(_OpenAIAdapter(client))
    bridge.is_anthropic = lambda: False  # type: ignore[method-assign]
    bridge._operations._resolve_model_vendor = lambda: vendor  # type: ignore[method-assign]
    return bridge, completions


def test_bridge_builds_cache_observation_context() -> None:
    bridge, _ = _bridge(ModelVendor.OPENAI)

    context = bridge._operations._with_cache_observation(
        {"session_id": "sess-cache"},
        system_prompt=f"stable\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\ndynamic tail",
        tools=[{"type": "function", "function": {"name": "weather", "description": "raw"}}],
        cache_whole_system=False,
    )

    observation = context["cache_observation"]
    assert observation["cache_strategy"] == "prompt_cache_key"
    assert observation["cache_eligible"] is True
    assert observation["tool_names"] == ["weather"]
    assert observation["system_head_hash"]
    assert "dynamic tail" not in str(observation)
    assert "raw" not in str(observation)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["chat_response", "chat_with_tools"])
@pytest.mark.parametrize(
    "vendor,context,body_key,header_key",
    [
        (
            ModelVendor.OPENAI,
            {"session_id": "session", "correlation_id": "fallback"},
            "session",
            None,
        ),
        (ModelVendor.GROK, {"correlation_id": "fallback"}, None, "fallback"),
        (ModelVendor.OPENAI, {}, None, None),
        (ModelVendor.GROK, {"session_id": " "}, None, None),
        *[
            (vendor, {"session_id": "session"}, None, None)
            for vendor in (
                ModelVendor.DEEPSEEK,
                ModelVendor.GLM,
                ModelVendor.KIMI,
                ModelVendor.GEMINI,
                ModelVendor.DASHSCOPE,
                ModelVendor.ANTHROPIC,
            )
        ],
    ],
)
async def test_vendor_routing_options_reach_real_request_builder(
    method, vendor, context, body_key, header_key
):
    bridge, completions = _bridge(vendor)
    kwargs = {
        "system_prompt": "sys",
        "messages": [{"role": "user", "content": "hi"}],
        "event_context": context,
    }
    if method == "chat_with_tools":
        kwargs["tools"] = [{"type": "function", "function": {"name": "bash"}}]
    await getattr(bridge, method)(**kwargs)
    assert completions.kwargs["messages"][-1] == {"role": "user", "content": "hi"}
    body = completions.kwargs.get("extra_body", {})
    headers = completions.kwargs.get("extra_headers", {})
    if body_key is None:
        assert "prompt_cache_key" not in body
    else:
        assert body["prompt_cache_key"] == body_key
    if header_key is None:
        assert "x-grok-conv-id" not in headers
    else:
        assert headers["x-grok-conv-id"] == header_key


# ---------------------------------------------------------------------------
# cache_system=True: mark a stable aux-call system prompt (routing/memory) (#100)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vendor,supports_marker",
    [
        (ModelVendor.DASHSCOPE, True),
        (ModelVendor.OPENAI, False),
        (ModelVendor.DEEPSEEK, False),
        (ModelVendor.GLM, False),
        (ModelVendor.GROK, False),
        (ModelVendor.GEMINI, False),
        (ModelVendor.KIMI, False),
        (ModelVendor.GENERIC, False),
    ],
)
@pytest.mark.parametrize("with_boundary", [False, True])
@pytest.mark.parametrize("cache_system", [False, True])
async def test_vendor_cache_policy_reaches_actual_request_payload(
    vendor, supports_marker, with_boundary, cache_system
):
    bridge, completions = _bridge(vendor)
    system = "STABLE SYSTEM" + (
        f"\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\nVOLATILE TAIL" if with_boundary else ""
    )
    await bridge.chat_response(
        system_prompt=system,
        messages=[{"role": "user", "content": "route this"}],
        cache_system=cache_system,
    )
    expected = (
        [{"type": "text", "text": "STABLE SYSTEM", "cache_control": {"type": "ephemeral"}}]
        if supports_marker and (with_boundary or cache_system)
        else "STABLE SYSTEM"
    )
    assert completions.kwargs["messages"][0] == {"role": "system", "content": expected}
    assert "VOLATILE TAIL" not in str(completions.kwargs["messages"][0])
    assert SYSTEM_PROMPT_CACHE_BOUNDARY not in str(completions.kwargs)
