"""
Tests for provider bridge normalization and provider-specific parameters.
"""
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.config.models import (
    LLMConcurrencyOverrideSettings,
    LLMProviderSettings,
    LLMSelectionSettings,
    LLMSettings,
)
from magi.llm.base import LLMAdapter
from magi.llm.anthropic import AnthropicAdapter
from magi.llm.openai import OpenAIAdapter
from magi.llm.provider_bridge import LLMProviderBridge


class DummyLLMAdapter(LLMAdapter):
    """Minimal adapter stub for bridge tests."""

    def __init__(
        self,
        model: str = "test-model",
        provider: str = "openai",
        client: Any = None,
        base_url: Optional[str] = None,
    ):
        self._model = model
        self._provider = provider
        self._client = client
        self._base_url = base_url
        self.chat_kwargs: Dict[str, Any] = {}

    async def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        return "generated"

    async def generate_stream(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[str]:
        if False:
            yield ""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        self.chat_kwargs = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }
        return "chat-ok"

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[str]:
        if False:
            yield ""

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def base_url(self) -> Optional[str]:
        return self._base_url


class DummyOpenAIClient:
    def __init__(self, response: Any):
        self.response = response
        self.kwargs: Dict[str, Any] = {}
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create),
        )

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class DummyAnthropicMessagesClient:
    def __init__(self, response: Any):
        self.response = response
        self.kwargs: Dict[str, Any] = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class RecordingConcurrencyLimiter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_with_limit(self, key: str, operation, *, limit: int | None = None):  # type: ignore[no-untyped-def]
        self.calls.append({"key": key, "limit": limit})
        return await operation()


def _build_test_llm_config(*, override_limit: int | None = None):
    llm_settings = LLMSettings(
        providers={
            "openai": LLMProviderSettings(
                enabled=True,
                provider_type="openai",
                display_name="OpenAI",
                api_key="sk-test",
                base_url="https://api.openai.com/v1",
            )
        },
        selections={
            "context_decider": LLMSelectionSettings(provider_id="openai", model="gpt-5.2"),
            "core": LLMSelectionSettings(provider_id="openai", model="gpt-5.2"),
            "embedding": LLMSelectionSettings(provider_id="openai", model="text-embedding-3-small"),
        },
    )
    if override_limit is not None:
        llm_settings.model_runtime_overrides["openai::api.openai.com::gpt-5.2::chat"] = (
            LLMConcurrencyOverrideSettings(max_concurrency=override_limit)
        )
    return SimpleNamespace(llm=SimpleNamespace(model_runtime_overrides=llm_settings.model_runtime_overrides))


@pytest.mark.asyncio
async def test_openai_tool_call_parsing_and_assistant_message():
    message = SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="file_read",
                    arguments='{"path":"README.md"}',
                ),
            )
        ],
    )
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="openai", client=client)
    bridge = LLMProviderBridge(llm)

    result = await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "read"}],
        tools=[{"type": "function", "function": {"name": "file_read"}}],
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "file_read"
    assert result.tool_calls[0].arguments["path"] == "README.md"
    assert result.assistant_message is not None
    assert result.assistant_message["role"] == "assistant"
    assert result.assistant_message["tool_calls"][0]["id"] == "call_1"


@pytest.mark.asyncio
async def test_openai_chat_response_converts_generic_image_blocks() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="done"), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="openai", client=client)
    bridge = LLMProviderBridge(llm)

    await bridge.chat_response(
        system_prompt="sys",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this image"},
                    {"type": "image", "mime_type": "image/png", "data": "ZmFrZS1pbWFnZQ=="},
                ],
            }
        ],
    )

    sent_content = client.kwargs["messages"][1]["content"]
    assert sent_content[0] == {"type": "text", "text": "describe this image"}
    assert sent_content[1]["type"] == "image_url"
    assert sent_content[1]["image_url"]["url"] == "data:image/png;base64,ZmFrZS1pbWFnZQ=="


@pytest.mark.asyncio
async def test_anthropic_path_converts_tool_result_messages():
    tool_block = SimpleNamespace(type="tool_use", id="toolu_1", name="bash", input={"command": "ls"})
    text_block = SimpleNamespace(type="text", text="done")
    response = SimpleNamespace(content=[tool_block, text_block])
    messages_client = DummyAnthropicMessagesClient(response=response)
    llm = DummyLLMAdapter(
        provider="anthropic",
        client=SimpleNamespace(messages=messages_client),
    )
    bridge = LLMProviderBridge(llm)
    bridge.is_anthropic = lambda: True

    result = await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[
            {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_0", "name": "bash", "input": {}}]},
            {"role": "tool", "tool_call_id": "toolu_0", "content": '{"success": true}'},
        ],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "toolu_1"
    assert result.tool_calls[0].name == "bash"
    sent_messages = messages_client.kwargs["messages"]
    assert sent_messages[1]["role"] == "user"
    assert sent_messages[1]["content"][0]["type"] == "tool_result"
    assert sent_messages[1]["content"][0]["tool_use_id"] == "toolu_0"


@pytest.mark.asyncio
async def test_anthropic_chat_response_converts_generic_image_blocks() -> None:
    text_block = SimpleNamespace(type="text", text="done")
    response = SimpleNamespace(content=[text_block], usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    messages_client = DummyAnthropicMessagesClient(response=response)
    llm = DummyLLMAdapter(
        provider="anthropic",
        client=SimpleNamespace(messages=messages_client),
    )
    bridge = LLMProviderBridge(llm)
    bridge.is_anthropic = lambda: True

    await bridge.chat_response(
        system_prompt="sys",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this image"},
                    {"type": "image", "mime_type": "image/png", "data": "ZmFrZS1pbWFnZQ=="},
                ],
            }
        ],
    )

    sent_content = messages_client.kwargs["messages"][0]["content"]
    assert sent_content[0] == {"type": "text", "text": "describe this image"}
    assert sent_content[1]["type"] == "image"
    assert sent_content[1]["source"]["type"] == "base64"
    assert sent_content[1]["source"]["media_type"] == "image/png"
    assert sent_content[1]["source"]["data"] == "ZmFrZS1pbWFnZQ=="


@pytest.mark.asyncio
async def test_glm_chat_disables_thinking_when_requested():
    llm = DummyLLMAdapter(provider="glm")
    bridge = LLMProviderBridge(llm)

    await bridge.chat(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        disable_thinking=True,
    )

    assert llm.chat_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_glm_chat_does_not_add_thinking_flag_when_enabled():
    llm = DummyLLMAdapter(provider="glm")
    bridge = LLMProviderBridge(llm)

    await bridge.chat(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        disable_thinking=False,
    )

    assert "extra_body" not in llm.chat_kwargs


@pytest.mark.asyncio
async def test_glm_chat_with_tools_disables_thinking_for_openai_compatible_path():
    message = SimpleNamespace(content="ok", tool_calls=[])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="glm", client=client)
    bridge = LLMProviderBridge(llm)

    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        disable_thinking=True,
    )

    assert client.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_chat_response_passes_json_mode_and_timeout_to_openai_compatible_clients() -> None:
    message = SimpleNamespace(content='{"summary":"ok"}', tool_calls=[], role="assistant")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="glm", client=client)
    bridge = LLMProviderBridge(llm)

    result = await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        json_mode=True,
        timeout_seconds=180.0,
    )

    assert result.content == '{"summary":"ok"}'
    assert client.kwargs["response_format"] == {"type": "json_object"}
    assert client.kwargs["timeout"] == 180.0


@pytest.mark.asyncio
async def test_chat_response_uses_shared_concurrency_limiter() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[], role="assistant")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(
        model="gpt-5.2",
        provider="openai",
        client=client,
        base_url="https://api.openai.com/v1",
    )
    limiter = RecordingConcurrencyLimiter()
    bridge = LLMProviderBridge(llm, concurrency_limiter=limiter)

    result = await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        timeout_seconds=180.0,
    )

    assert result.content == "ok"
    assert limiter.calls == [
        {
            "key": "openai::api.openai.com::gpt-5.2::chat",
            "limit": 2,
        }
    ]


@pytest.mark.asyncio
async def test_chat_response_passes_shared_override_before_registry_default_before_fallback(monkeypatch) -> None:
    message = SimpleNamespace(content="ok", tool_calls=[], role="assistant")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(
        model="gpt-5.2",
        provider="openai",
        client=client,
        base_url="https://api.openai.com/v1",
    )
    limiter = RecordingConcurrencyLimiter()
    bridge = LLMProviderBridge(llm, concurrency_limiter=limiter)

    override_config = _build_test_llm_config(override_limit=7)
    default_config = _build_test_llm_config()

    monkeypatch.setattr("magi.llm.provider_bridge_options.get_config", lambda: override_config, raising=False)

    await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert limiter.calls[-1]["limit"] == 7

    monkeypatch.setattr("magi.llm.provider_bridge_options.get_config", lambda: default_config, raising=False)

    await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert limiter.calls[-1]["limit"] == 2

    fallback_client = DummyOpenAIClient(response=response)
    fallback_llm = DummyLLMAdapter(
        model="test-model",
        provider="custom",
        client=fallback_client,
        base_url="https://gateway.example.com/v1",
    )
    fallback_bridge = LLMProviderBridge(fallback_llm, concurrency_limiter=limiter)

    monkeypatch.setattr("magi.llm.provider_bridge_options.get_config", lambda: _build_test_llm_config(), raising=False)

    await fallback_bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert limiter.calls[-1]["limit"] == 4


@pytest.mark.asyncio
async def test_chat_with_tools_passes_timeout_to_openai_compatible_clients() -> None:
    message = SimpleNamespace(content="", tool_calls=[], role="assistant")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="openai", client=client)
    bridge = LLMProviderBridge(llm)

    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        timeout_seconds=180.0,
    )

    assert client.kwargs["timeout"] == 180.0


def test_real_adapters_expose_base_url_for_host_aware_keying() -> None:
    openai_adapter = OpenAIAdapter(
        api_key="sk-test",
        model="gpt-5.2",
        base_url="https://gateway.example.com/v1",
    )
    anthropic_adapter = AnthropicAdapter(
        api_key="sk-test",
        model="claude-sonnet-4-6",
        api_base="https://proxy.example.com/v1",
    )

    assert openai_adapter.base_url == "https://gateway.example.com/v1"
    assert anthropic_adapter.base_url == "https://proxy.example.com/v1"


@pytest.mark.asyncio
async def test_chat_response_exposes_openai_metadata_for_empty_content():
    message = SimpleNamespace(content="", tool_calls=[], role="assistant")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4, total_tokens=16),
    )
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="glm", client=client)
    bridge = LLMProviderBridge(llm)

    result = await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        disable_thinking=False,
    )

    assert result.content == ""
    assert result.metadata is not None
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["has_content"] is False
    assert result.metadata["provider"] == "glm"
    assert result.metadata["raw_message"]["content"] == ""
    assert result.usage is not None
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 4
    assert result.usage.total_tokens == 16


@pytest.mark.asyncio
async def test_chat_response_exposes_trace_metrics() -> None:
    message = SimpleNamespace(content="hello", tool_calls=[], role="assistant")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4, total_tokens=16),
    )
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="openai", client=client)
    bridge = LLMProviderBridge(llm)

    result = await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        disable_thinking=False,
    )

    trace_metrics = result.metadata["trace_metrics"]
    assert trace_metrics["provider"] == "openai"
    assert trace_metrics["model"] == "test-model"
    assert trace_metrics["input_tokens"] == 12
    assert trace_metrics["output_tokens"] == 4
    assert trace_metrics["total_tokens"] == 16
    assert trace_metrics["thinking_enabled"] is True
    assert trace_metrics["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_openai_content_parses_legacy_tool_call_blocks() -> None:
    legacy_content = (
        "<tool_call>agent"
        "<arg_key>timeout_seconds</arg_key><arg_value>30</arg_value>"
        "<arg_key>run_in_background</arg_key><arg_value>false</arg_value>"
        "<arg_key>description</arg_key><arg_value>analyze repo</arg_value>"
        "</tool_call>"
    )
    message = SimpleNamespace(content=legacy_content, tool_calls=[])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="openai", client=client)
    bridge = LLMProviderBridge(llm)

    result = await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "run tools"}],
        tools=[{"type": "function", "function": {"name": "agent"}}],
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "agent"
    assert result.tool_calls[0].arguments["timeout_seconds"] == 30
    assert result.tool_calls[0].arguments["run_in_background"] is False
    assert result.tool_calls[0].arguments["description"] == "analyze repo"


@pytest.mark.asyncio
async def test_bridge_publishes_usage_event_with_prompt_and_completion_tokens(monkeypatch) -> None:
    published_payloads = []

    async def fake_publish(payload, publisher=None):
        _ = publisher
        published_payloads.append(payload)

    monkeypatch.setattr("magi.llm.provider_bridge.publish_llm_call_event", fake_publish)

    message = SimpleNamespace(content="hello", tool_calls=[], role="assistant")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, total_tokens=28),
    )
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="openai", client=client)
    bridge = LLMProviderBridge(llm)

    await bridge.chat_response(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        event_context={
            "request_id": "req123",
            "request_kind": "context_decider",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "agent_id": "agent-1",
        },
    )

    assert len(published_payloads) == 1
    payload = published_payloads[0]
    assert payload.request_id == "req123"
    assert payload.request_kind == "context_decider"
    assert payload.prompt_tokens == 20
    assert payload.completion_tokens == 8
    assert payload.total_tokens == 28
    assert payload.session_id == "session-1"


@pytest.mark.asyncio
async def test_dashscope_chat_disables_thinking_when_requested():
    llm = DummyLLMAdapter(provider="dashscope")
    bridge = LLMProviderBridge(llm)

    await bridge.chat(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        disable_thinking=True,
    )

    assert llm.chat_kwargs["extra_body"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_dashscope_chat_enables_thinking_when_not_disabled():
    llm = DummyLLMAdapter(provider="dashscope")
    bridge = LLMProviderBridge(llm)

    await bridge.chat(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        disable_thinking=False,
    )

    assert llm.chat_kwargs["extra_body"] == {"enable_thinking": True}


@pytest.mark.asyncio
async def test_dashscope_chat_with_tools_disables_thinking_for_openai_compatible_path():
    message = SimpleNamespace(content="ok", tool_calls=[])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
    client = DummyOpenAIClient(response=response)
    llm = DummyLLMAdapter(provider="dashscope", client=client)
    bridge = LLMProviderBridge(llm)

    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        disable_thinking=True,
    )

    assert client.kwargs["extra_body"] == {"enable_thinking": False}
