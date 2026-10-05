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
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("redacted", [False, True])
async def test_thinking_blocks_survive_response_and_followup_history(streaming, redacted):
    head = (
        {"type": "redacted_thinking", "data": "ENCRYPTED"}
        if redacted
        else {"type": "thinking", "thinking": "Step one. Step two.", "signature": "sig-stream"}
    )
    tool = {"type": "tool_use", "id": "toolu_9", "name": "bash", "input": {"command": "ls"}}
    if streaming:
        events = _thinking_then_tool_events()
        if redacted:
            events = [
                events[0],
                SimpleNamespace(
                    type="content_block_start", index=0, content_block=SimpleNamespace(**head)
                ),
                SimpleNamespace(type="content_block_stop", index=0),
                *events[6:],
            ]
        bridge = _bridge(_StreamingMessagesClient(events))
        streamed = await bridge.chat_with_tools_stream(
            system_prompt="sys",
            messages=[{"role": "user", "content": "do it"}],
            tools=[{"type": "function", "function": {"name": "bash"}}],
        )
        assistant = streamed.provider_response.assistant_message
    else:
        response = SimpleNamespace(
            content=[SimpleNamespace(**head), SimpleNamespace(**tool)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        bridge = _bridge(_RecordingMessagesClient(response))
        result = await bridge.chat_with_tools(
            system_prompt="sys",
            messages=[{"role": "user", "content": "do it"}],
            tools=[{"type": "function", "function": {"name": "bash"}}],
        )
        assistant = result.assistant_message
    assert assistant["content"] == [head, tool]
    next_client = _RecordingMessagesClient(
        SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
    )
    await _bridge(next_client).chat_with_tools(
        system_prompt="sys",
        messages=[
            {"role": "user", "content": "do it"},
            assistant,
            {"role": "tool", "tool_call_id": "toolu_9", "content": "done"},
        ],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )
    [resent] = [
        message for message in next_client.kwargs["messages"] if message["role"] == "assistant"
    ]
    assert resent["content"][0] == head
    assert resent["content"][1]["id"] == "toolu_9"
    assert resent["content"][1]["input"] == {"command": "ls"}


# --------------------------------------------------------------------------
# Converter round-trip (_convert_messages_to_anthropic)
# --------------------------------------------------------------------------


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
