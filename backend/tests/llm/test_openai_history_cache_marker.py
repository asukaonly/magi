"""Rolling history cache breakpoint on the OpenAI-compatible path (#100 / #110).

DashScope honors message-level ``cache_control`` (verified by direct probe), so
the rolling history breakpoint — already applied on the Anthropic native path
(#121) — is extended to the OpenAI-compatible builders for marker vendors. This
caches the conversation history (not just the system head) on DashScope chats.

Non-marker OpenAI-compatible vendors (openai/deepseek/glm/grok/gemini/kimi) must
NOT receive message markers — they'd be ignored or rejected. Tool-role messages
are never marked on this path (compat endpoints expect plain-string tool content).
"""

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.config.models import ModelVendor
from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import LLMProviderBridge
from magi.utils.model_context_messages import build_working_context_message

SYS = f"STABLE HEAD{SYSTEM_PROMPT_CACHE_BOUNDARY}"
WORKING_CONTEXT = build_working_context_message("MEMORY TAIL")
assert WORKING_CONTEXT is not None


class _OpenAIAdapter(LLMAdapter):
    def __init__(self, client: Any, provider: str = "dashscope") -> None:
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
        return "qwen3.7-plus"

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def base_url(self) -> Optional[str]:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


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


def _has_cc(message: Dict[str, Any]) -> bool:
    content = message.get("content")
    if isinstance(content, list):
        return any(isinstance(b, dict) and "cache_control" in b for b in content)
    return False


@pytest.mark.asyncio
async def test_dashscope_marks_history_boundary_not_current_turn() -> None:
    bridge, completions = _bridge(ModelVendor.DASHSCOPE)
    await bridge.chat_response(
        system_prompt=SYS,
        messages=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            WORKING_CONTEXT,
            {"role": "user", "content": "u2"},
        ],
    )
    sent = completions.kwargs["messages"]
    assert "_magi_context_kind" not in str(sent)
    # The breakpoint lands on the prior accepted assistant turn (a1).
    a1 = next(m for m in sent if m.get("role") == "assistant")
    assert _has_cc(a1)
    # the current Working Context and user turn are NOT breakpoints.
    u2 = [m for m in sent if m.get("role") == "user"][-1]
    assert not _has_cc(u2)


@pytest.mark.asyncio
async def test_non_marker_openai_vendor_gets_no_message_markers() -> None:
    bridge, completions = _bridge(ModelVendor.DEEPSEEK)
    await bridge.chat_response(
        system_prompt=SYS,
        messages=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            WORKING_CONTEXT,
            {"role": "user", "content": "u2"},
        ],
    )
    sent = completions.kwargs["messages"]
    # No marker vendor -> no message-level cache_control anywhere in the stream.
    assert not any(_has_cc(m) for m in sent if m.get("role") != "system")


@pytest.mark.asyncio
async def test_tool_role_messages_are_never_marked() -> None:
    bridge, completions = _bridge(ModelVendor.DASHSCOPE)
    await bridge.chat_with_tools(
        system_prompt=SYS,
        messages=[
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "content": '{"ok": true}'},
            WORKING_CONTEXT,
            {"role": "user", "content": "u2"},
        ],
        tools=[{"type": "function", "function": {"name": "bash"}}],
    )
    sent = completions.kwargs["messages"]
    # tool-role messages must keep plain-string content (no cache_control list).
    for m in sent:
        if m.get("role") == "tool":
            assert not _has_cc(m)
            assert isinstance(m.get("content"), str)
