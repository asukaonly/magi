"""Anthropic rolling history cache breakpoint (#110 / #100 follow-up).

After P2a moved per-turn context out of the system prompt and onto the last
user message, the system head + conversation history form a byte-stable prefix.
DashScope auto-caches such a prefix implicitly, but Anthropic requires an
explicit ``cache_control`` marker. We place a rolling ``ephemeral`` breakpoint
on the message *before* the turn-context-bearing message — the stable history
boundary that is reusable across turns — so older history caches while the
volatile per-turn context (and the current question) stays uncached.
"""

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import LLMProviderBridge

SYS = f"STABLE HEAD{SYSTEM_PROMPT_CACHE_BOUNDARY}"
TURN_CONTEXT = "<turn_context>\nMEMORY + TIME TAIL\n</turn_context>"


class _AnthropicAdapter(LLMAdapter):
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
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: Dict[str, Any] = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _bridge(client: _RecordingMessagesClient) -> LLMProviderBridge:
    llm = _AnthropicAdapter(client=SimpleNamespace(messages=client))
    bridge = LLMProviderBridge(llm)
    bridge.is_anthropic = lambda: True  # type: ignore[method-assign]
    return bridge


def _text_response() -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


@pytest.mark.asyncio
async def test_request_marks_stable_history_before_turn_context() -> None:
    client = _RecordingMessagesClient(_text_response())
    bridge = _bridge(client)

    await bridge.chat_response(
        system_prompt=SYS,
        messages=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": TURN_CONTEXT},
            {"role": "user", "content": "u2"},
        ],
    )

    sent = client.kwargs["messages"]
    # The explicit turn-context snapshot is index 2, so the breakpoint lands on
    # the stable message immediately before it (a1, index 1).
    assert sent[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # The turn-context-bearing current turn is NOT a breakpoint (volatile).
    assert "cache_control" not in str(sent[2:])
    # Older history before the boundary stays unmarked.
    assert "cache_control" not in str(sent[0])


@pytest.mark.asyncio
async def test_no_history_breakpoint_on_first_turn() -> None:
    client = _RecordingMessagesClient(_text_response())
    bridge = _bridge(client)

    await bridge.chat_response(
        system_prompt=SYS,
        messages=[
            {"role": "user", "content": TURN_CONTEXT},
            {"role": "user", "content": "only turn"},
        ],
    )

    # No prior history to cache; the single (turn-context-bearing) message must
    # not carry a breakpoint. System head marker lives in kwargs["system"], not here.
    assert "cache_control" not in str(client.kwargs["messages"])


@pytest.mark.asyncio
async def test_system_head_uses_1h_ttl() -> None:
    client = _RecordingMessagesClient(_text_response())
    bridge = _bridge(client)

    await bridge.chat_response(
        system_prompt=SYS,
        messages=[{"role": "user", "content": "hi"}],
    )

    # The stable system head is written with a 1h TTL (it is reused across turns
    # and conversations, so the 2x write amortizes); message markers stay 5m.
    system = client.kwargs["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


@pytest.mark.asyncio
async def test_tool_loop_marks_pre_turn_history_and_tool_result_tail() -> None:
    client = _RecordingMessagesClient(_text_response())
    bridge = _bridge(client)

    # A completed prior turn, then the current human turn that kicked off a tool
    # loop (tool results are role "tool"). Two message breakpoints: the rolling
    # history boundary (a1, reused across turns) and the growing tool-result tail
    # (reused across iterations of THIS turn's loop). The mid-loop tool_use turn
    # is never a breakpoint.
    await bridge.chat_with_tools(
        system_prompt=SYS,
        messages=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": TURN_CONTEXT},
            {"role": "user", "content": "u2"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}],
            },
            {"role": "tool", "tool_call_id": "t1", "content": '{"success": true}'},
        ],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )

    sent = client.kwargs["messages"]
    # rolling history boundary: the explicit context follows a1.
    assert sent[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # the mid-loop assistant tool_use turn is NOT a breakpoint.
    assert "cache_control" not in str(sent[4])
    # the tool-result tail IS a breakpoint (5m), so the next loop iteration hits.
    assert sent[5]["content"][-1]["cache_control"] == {"type": "ephemeral"}
