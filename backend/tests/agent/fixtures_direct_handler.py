"""Fixtures for DirectLLMHandler integration tests.

Construct a DirectLLMHandler with a stub PromptService whose
call_llm / call_llm_stream emulate the cancellable-client behavior
without requiring a real LLM provider.

``DirectLLMHandler`` accepts any duck-typed dependency container that
exposes a ``prompt_service`` attribute; ``_DirectLLMDependencies`` is a
thin ``SimpleNamespace`` wrapper defined here for test clarity.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import AsyncIterator, Callable, Iterable

from magi.agent.run_control import RunControl
from magi.agent.task_agents.handlers.contracts import (
    ChatRuntimeContext,
    IntentDecision,
)
from magi.agent.task_agents.handlers.direct_handler import DirectLLMHandler
from magi.agent.task_agents.common.contracts import (
    DirectLLMRequest,
    ExecutionMode,
    GenericFactPayload,
    IncomingFactKind,
    ToolSelection,
)
from magi.config.models import ThinkingDepth
from magi.llm.cancellable_client import CancellationRaised, RetractRaised
from magi.llm.streaming_events import LLMStreamEvent


def _DirectLLMDependencies(*, prompt_service: object) -> SimpleNamespace:
    """Return a duck-typed dependency container accepted by DirectLLMHandler."""
    return SimpleNamespace(prompt_service=prompt_service)


class _StubPromptServiceStream:
    """Stub PromptService that emulates CancellableLLMClient stream behavior."""

    def __init__(self, chunks: Iterable[str], chunk_delay_seconds: float = 0.0) -> None:
        """Initialise with chunk list and optional per-chunk delay."""
        self._chunks = list(chunks)
        self._delay = chunk_delay_seconds
        self._gates: list[asyncio.Event] | None = None

    def with_gates(self, gates: list[asyncio.Event]) -> "_StubPromptServiceStream":
        """Attach per-chunk gates; each gate must be set before that chunk yields."""
        self._gates = gates
        return self

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        thinking_depth: ThinkingDepth | None = None,
        llm_trace_callback=None,
        event_context: dict | None = None,
        control: RunControl | None = None,
    ) -> str:
        """Non-streaming call; pre-polls control before returning joined chunks."""
        if control is not None:
            if control.retract_signal.is_requested():
                raise RetractRaised(control.retract_signal.payload)
            if await control.cancel_token.is_cancelled():
                raise CancellationRaised(control.cancel_token.reason)
        return "".join(self._chunks)

    async def call_llm_stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        thinking_depth: ThinkingDepth | None = None,
        event_context: dict | None = None,
        control: RunControl | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming call; mirrors CancellableLLMClient.stream pre-poll + per-chunk poll."""
        if control is not None:
            if control.retract_signal.is_requested():
                raise RetractRaised(control.retract_signal.payload)
            if await control.cancel_token.is_cancelled():
                raise CancellationRaised(control.cancel_token.reason)

        for i, chunk in enumerate(self._chunks):
            if self._gates is not None and i < len(self._gates):
                await self._gates[i].wait()
            else:
                await asyncio.sleep(self._delay)
            if control is not None:
                if control.retract_signal.is_requested():
                    raise RetractRaised(control.retract_signal.payload)
                if await control.cancel_token.is_cancelled():
                    raise CancellationRaised(control.cancel_token.reason)
            yield LLMStreamEvent(kind="text_delta", text=chunk)


class _StubPromptServiceCall:
    """Stub PromptService.call_llm with a call counter for non-streaming tests."""

    def __init__(self, response_text: str) -> None:
        """Initialise with the text that call_llm would return."""
        self._response = response_text
        self._calls = 0

    def call_count(self) -> int:
        """Return the number of times call_llm was invoked."""
        return self._calls

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        thinking_depth: ThinkingDepth | None = None,
        llm_trace_callback=None,
        event_context: dict | None = None,
        control: RunControl | None = None,
    ) -> str:
        """Non-streaming call; pre-polls control, then increments counter and returns text."""
        if control is not None:
            if control.retract_signal.is_requested():
                raise RetractRaised(control.retract_signal.payload)
            if await control.cancel_token.is_cancelled():
                raise CancellationRaised(control.cancel_token.reason)
        self._calls += 1
        return self._response

    async def call_llm_stream(self, **_kwargs):
        """Not used; raises to catch accidental wiring in non-streaming tests."""
        raise AssertionError("call_llm_stream should not be called in non-streaming test")
        yield  # unreachable; makes this an async generator for type checking


def _minimal_context(control: RunControl, streaming_enabled: bool) -> ChatRuntimeContext:
    """Build a minimal ChatRuntimeContext for tests with no optional dependencies."""
    return ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="test-agent",
        agent_type="chat",
        runtime_key="chat:test",
        user_id="user-1",
        session_id="session-1",
        history_key="hk-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        streaming_chat_enabled=streaming_enabled,
        core_model_supports_vision=True,
        control=control,
    )


def _minimal_request(control: RunControl, streaming_enabled: bool) -> DirectLLMRequest:
    """Build a minimal DirectLLMRequest with a pre-set RunControl."""
    ctx = _minimal_context(control, streaming_enabled)
    intent = IntentDecision(
        intent="chat",
        execution_mode=ExecutionMode.DIRECT_LLM,
        difficulty="normal",
        tools=[],
    )
    tool_sel = ToolSelection()
    return DirectLLMRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=ctx,
        intent=intent,
        tool_selection=tool_sel,
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        thinking_depth=ThinkingDepth.NONE,
    )


def build_minimal_direct_request(
    *, control: RunControl, streaming_enabled: bool
) -> DirectLLMRequest:
    """Public entry-point for building a minimal DirectLLMRequest in tests."""
    return _minimal_request(control, streaming_enabled)


def build_direct_handler_with_slow_stream(
    *, chunks: list[str], chunk_delay_seconds: float = 0.0,
) -> tuple[DirectLLMHandler, _StubPromptServiceStream]:
    """Return a DirectLLMHandler backed by a slow-streaming stub prompt service."""
    prompt_service = _StubPromptServiceStream(chunks, chunk_delay_seconds)
    deps = _DirectLLMDependencies(prompt_service=prompt_service)
    handler = DirectLLMHandler(deps)
    return handler, prompt_service


def build_direct_handler_with_gated_stream(
    *, chunks: list[str],
) -> tuple[DirectLLMHandler, _StubPromptServiceStream, list[asyncio.Event]]:
    """Return a DirectLLMHandler with per-chunk asyncio.Event gates for fine timing control."""
    gates = [asyncio.Event() for _ in chunks]
    prompt_service = _StubPromptServiceStream(chunks).with_gates(gates)
    deps = _DirectLLMDependencies(prompt_service=prompt_service)
    handler = DirectLLMHandler(deps)
    return handler, prompt_service, gates


def build_direct_handler_with_simple_call(
    *, response_text: str,
) -> tuple[DirectLLMHandler, _StubPromptServiceCall, Callable[[], int]]:
    """Return a DirectLLMHandler backed by a counting stub for non-streaming tests."""
    prompt_service = _StubPromptServiceCall(response_text)
    deps = _DirectLLMDependencies(prompt_service=prompt_service)
    handler = DirectLLMHandler(deps)
    return handler, prompt_service, prompt_service.call_count
