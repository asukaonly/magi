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
from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import LLMProviderBridge
from magi.llm.provider_bridge.cache_routing import (
    cache_routing_request_kwargs,
    routing_key_from_event_context,
)


# --- pure functions ---


def test_routing_key_prefers_session_id() -> None:
    assert routing_key_from_event_context({"session_id": "s1"}) == "s1"
    # correlation_id is the fallback when no session_id
    assert routing_key_from_event_context({"correlation_id": "c1"}) == "c1"
    assert routing_key_from_event_context({"session_id": "s1", "correlation_id": "c1"}) == "s1"


def test_routing_key_none_when_absent_or_empty() -> None:
    assert routing_key_from_event_context(None) is None
    assert routing_key_from_event_context({}) is None
    assert routing_key_from_event_context({"session_id": ""}) is None
    assert routing_key_from_event_context({"session_id": "  "}) is None


def test_routing_kwargs_openai_uses_prompt_cache_key_body() -> None:
    assert cache_routing_request_kwargs(ModelVendor.OPENAI, "s1") == {
        "extra_body": {"prompt_cache_key": "s1"}
    }


def test_routing_kwargs_grok_uses_conv_id_header() -> None:
    assert cache_routing_request_kwargs(ModelVendor.GROK, "s1") == {
        "extra_headers": {"x-grok-conv-id": "s1"}
    }


def test_routing_kwargs_empty_for_other_vendors_or_no_key() -> None:
    for vendor in (ModelVendor.DEEPSEEK, ModelVendor.GLM, ModelVendor.KIMI,
                   ModelVendor.GEMINI, ModelVendor.DASHSCOPE, ModelVendor.ANTHROPIC):
        assert cache_routing_request_kwargs(vendor, "s1") == {}
    assert cache_routing_request_kwargs(ModelVendor.OPENAI, None) == {}
    assert cache_routing_request_kwargs(ModelVendor.GROK, "") == {}


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


@pytest.mark.asyncio
async def test_chat_with_tools_injects_openai_prompt_cache_key() -> None:
    bridge, completions = _bridge(ModelVendor.OPENAI)
    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "bash"}}],
        event_context={"session_id": "sess-abc"},
    )
    assert completions.kwargs["extra_body"]["prompt_cache_key"] == "sess-abc"


@pytest.mark.asyncio
async def test_chat_with_tools_injects_grok_conv_id_header() -> None:
    bridge, completions = _bridge(ModelVendor.GROK)
    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "bash"}}],
        event_context={"session_id": "sess-xyz"},
    )
    assert completions.kwargs["extra_headers"]["x-grok-conv-id"] == "sess-xyz"


@pytest.mark.asyncio
async def test_chat_response_injects_routing_key() -> None:
    bridge, completions = _bridge(ModelVendor.OPENAI)
    await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        event_context={"session_id": "sess-r"},
    )
    assert completions.kwargs["extra_body"]["prompt_cache_key"] == "sess-r"


@pytest.mark.asyncio
async def test_no_routing_key_when_session_absent() -> None:
    bridge, completions = _bridge(ModelVendor.OPENAI)
    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        event_context={},
    )
    # extra_body may exist for other reasons (e.g. reasoning options); just no key
    assert "prompt_cache_key" not in completions.kwargs.get("extra_body", {})


@pytest.mark.asyncio
async def test_no_routing_key_for_unsupported_vendor() -> None:
    bridge, completions = _bridge(ModelVendor.DEEPSEEK)
    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        event_context={"session_id": "sess-d"},
    )
    assert "prompt_cache_key" not in completions.kwargs.get("extra_body", {})
    assert "x-grok-conv-id" not in completions.kwargs.get("extra_headers", {})


# ---------------------------------------------------------------------------
# cache_system=True: mark a stable aux-call system prompt (routing/memory) (#100)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_system_marks_stable_system_for_marker_vendor() -> None:
    bridge, completions = _bridge(ModelVendor.DASHSCOPE)
    await bridge.chat_response(
        system_prompt="STABLE ROUTING PROMPT (no boundary)",
        messages=[{"role": "user", "content": "route this"}],
        cache_system=True,
    )
    system_msg = completions.kwargs["messages"][0]
    assert system_msg["role"] == "system"
    assert isinstance(system_msg["content"], list)
    assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_cache_system_off_leaves_plain_system() -> None:
    bridge, completions = _bridge(ModelVendor.DASHSCOPE)
    await bridge.chat_response(
        system_prompt="STABLE ROUTING PROMPT",
        messages=[{"role": "user", "content": "route"}],
    )
    assert completions.kwargs["messages"][0]["content"] == "STABLE ROUTING PROMPT"


@pytest.mark.asyncio
async def test_cache_system_noop_for_non_marker_vendor() -> None:
    bridge, completions = _bridge(ModelVendor.DEEPSEEK)
    await bridge.chat_response(
        system_prompt="STABLE ROUTING PROMPT",
        messages=[{"role": "user", "content": "route"}],
        cache_system=True,
    )
    assert completions.kwargs["messages"][0]["content"] == "STABLE ROUTING PROMPT"
