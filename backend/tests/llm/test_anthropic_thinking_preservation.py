"""Anthropic extended-thinking block preservation (#99).

When extended thinking is enabled and the model also calls a tool, the
assistant turn contains thinking / redacted_thinking blocks *before* the
tool_use block. Anthropic requires those blocks (with their signatures) to be
echoed back verbatim on the follow-up request — both for correctness (the API
rejects tool turns whose thinking blocks were stripped) and for prompt-cache
stability. Both the non-streaming parser and the streaming reconstructor must
capture them; the converter must re-send them.
"""

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import LLMProviderBridge


class _AnthropicAdapter(LLMAdapter):
    """Minimal anthropic-flavored adapter stub exposing a fake messages client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def generate(self, prompt: str, max_tokens: Optional[int] = None,
                       temperature: float = 0.7, **kwargs) -> str:
        return "generated"

    async def generate_stream(self, prompt: str, max_tokens: Optional[int] = None,
                              temperature: float = 0.7, **kwargs) -> AsyncIterator[str]:
        if False:
            yield ""

    async def chat(self, messages: List[Dict[str, str]], max_tokens: Optional[int] = None,
                   temperature: float = 0.7, **kwargs) -> str:
        return "chat-ok"

    async def chat_stream(self, messages: List[Dict[str, str]], max_tokens: Optional[int] = None,
                          temperature: float = 0.7, **kwargs) -> AsyncIterator[str]:
        if False:
            yield ""

    @property
    def model_name(self) -> str:
        return "claude-opus-4-8"

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def base_url(self) -> Optional[str]:
        return None


class _RecordingMessagesClient:
    """Records create() kwargs and returns a canned non-streaming response."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: Dict[str, Any] = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _StreamingMessagesClient:
    """Returns a canned sequence of Anthropic streaming events."""

    def __init__(self, events: List[Any]) -> None:
        self.events = events
        self.kwargs: Dict[str, Any] = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs

        async def _gen():
            for event in self.events:
                yield event

        return _gen()


def _bridge(messages_client: Any) -> LLMProviderBridge:
    llm = _AnthropicAdapter(client=SimpleNamespace(messages=messages_client))
    bridge = LLMProviderBridge(llm)
    bridge.is_anthropic = lambda: True  # type: ignore[method-assign]
    return bridge


# --------------------------------------------------------------------------
# Non-streaming parser (_parse_anthropic_response)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_streaming_preserves_thinking_block_before_tool_use() -> None:
    thinking = SimpleNamespace(type="thinking", thinking="Let me reason.", signature="sig-abc")
    tool = SimpleNamespace(type="tool_use", id="toolu_1", name="bash", input={"command": "ls"})
    response = SimpleNamespace(
        content=[thinking, tool],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    bridge = _bridge(_RecordingMessagesClient(response))

    result = await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "do it"}],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    content = result.assistant_message["content"]
    types = [b["type"] for b in content]
    assert types == ["thinking", "tool_use"]
    assert content[0] == {"type": "thinking", "thinking": "Let me reason.", "signature": "sig-abc"}


@pytest.mark.asyncio
async def test_non_streaming_preserves_redacted_thinking_block() -> None:
    redacted = SimpleNamespace(type="redacted_thinking", data="ENCRYPTED")
    tool = SimpleNamespace(type="tool_use", id="toolu_1", name="bash", input={})
    response = SimpleNamespace(
        content=[redacted, tool],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    bridge = _bridge(_RecordingMessagesClient(response))

    result = await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "do it"}],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    content = result.assistant_message["content"]
    assert content[0] == {"type": "redacted_thinking", "data": "ENCRYPTED"}
    assert content[1]["type"] == "tool_use"


# --------------------------------------------------------------------------
# Converter round-trip (_convert_messages_to_anthropic)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stored_thinking_block_resent_to_anthropic_verbatim() -> None:
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    messages_client = _RecordingMessagesClient(response)
    bridge = _bridge(messages_client)

    stored_assistant = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "prev reasoning", "signature": "sig-xyz"},
            {"type": "tool_use", "id": "toolu_0", "name": "bash", "input": {}},
        ],
    }
    await bridge.chat_with_tools(
        system_prompt="sys",
        messages=[
            stored_assistant,
            {"role": "tool", "tool_call_id": "toolu_0", "content": '{"success": true}'},
        ],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    sent = messages_client.kwargs["messages"]
    assert sent[0]["role"] == "assistant"
    assert sent[0]["content"][0] == {
        "type": "thinking",
        "thinking": "prev reasoning",
        "signature": "sig-xyz",
    }


# --------------------------------------------------------------------------
# Streaming reconstructor (_stream_anthropic_with_tools)
# --------------------------------------------------------------------------


def _thinking_then_tool_events() -> List[Any]:
    return [
        SimpleNamespace(type="message_start",
                        message=SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=0))),
        SimpleNamespace(type="content_block_start", index=0,
                        content_block=SimpleNamespace(type="thinking")),
        SimpleNamespace(type="content_block_delta", index=0,
                        delta=SimpleNamespace(type="thinking_delta", thinking="Step one. ")),
        SimpleNamespace(type="content_block_delta", index=0,
                        delta=SimpleNamespace(type="thinking_delta", thinking="Step two.")),
        SimpleNamespace(type="content_block_delta", index=0,
                        delta=SimpleNamespace(type="signature_delta", signature="sig-stream")),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(type="content_block_start", index=1,
                        content_block=SimpleNamespace(type="tool_use", id="toolu_9", name="bash")),
        SimpleNamespace(type="content_block_delta", index=1,
                        delta=SimpleNamespace(type="input_json_delta", partial_json='{"command": "ls"}')),
        SimpleNamespace(type="content_block_stop", index=1),
        SimpleNamespace(type="message_delta", usage=SimpleNamespace(output_tokens=5)),
        SimpleNamespace(type="message_stop"),
    ]


@pytest.mark.asyncio
async def test_streaming_preserves_thinking_block_with_signature_before_tool_use() -> None:
    bridge = _bridge(_StreamingMessagesClient(_thinking_then_tool_events()))

    result = await bridge.chat_with_tools_stream(
        system_prompt="sys",
        messages=[{"role": "user", "content": "do it"}],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    content = result.provider_response.assistant_message["content"]
    types = [b["type"] for b in content]
    assert "thinking" in types
    assert "tool_use" in types
    assert types.index("thinking") < types.index("tool_use")
    thinking = next(b for b in content if b["type"] == "thinking")
    assert thinking["thinking"] == "Step one. Step two."
    assert thinking["signature"] == "sig-stream"


@pytest.mark.asyncio
async def test_streaming_preserves_redacted_thinking_block() -> None:
    events = [
        SimpleNamespace(type="message_start",
                        message=SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=0))),
        SimpleNamespace(type="content_block_start", index=0,
                        content_block=SimpleNamespace(type="redacted_thinking", data="ENCRYPTED")),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(type="content_block_start", index=1,
                        content_block=SimpleNamespace(type="tool_use", id="toolu_9", name="bash")),
        SimpleNamespace(type="content_block_delta", index=1,
                        delta=SimpleNamespace(type="input_json_delta", partial_json="{}")),
        SimpleNamespace(type="content_block_stop", index=1),
        SimpleNamespace(type="message_stop"),
    ]
    bridge = _bridge(_StreamingMessagesClient(events))

    result = await bridge.chat_with_tools_stream(
        system_prompt="sys",
        messages=[{"role": "user", "content": "do it"}],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    content = result.provider_response.assistant_message["content"]
    assert content[0] == {"type": "redacted_thinking", "data": "ENCRYPTED"}
    assert content[1]["type"] == "tool_use"
