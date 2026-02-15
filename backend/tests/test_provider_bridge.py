"""
Tests for provider bridge normalization and provider-specific parameters.
"""
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import LLMProviderBridge


class DummyLLMAdapter(LLMAdapter):
    """Minimal adapter stub for bridge tests."""

    def __init__(
        self,
        model: str = "test-model",
        provider: str = "openai",
        client: Any = None,
    ):
        self._model = model
        self._provider = provider
        self._client = client
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
async def test_glm_chat_adds_thinking_disable_flag_when_requested():
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
