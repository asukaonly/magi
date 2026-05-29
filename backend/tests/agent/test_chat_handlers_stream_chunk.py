"""Phase G+1: DirectLLMHandler routes text_delta events through
``coordinator.dispatch_stream_chunk`` (in addition to the legacy
``notifier.emit_stream_event`` path). After the stream ends — normally,
via cancellation, or via retraction — the handler must dispatch one
final ``is_final=True`` boundary chunk so channels can flush/close.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import AsyncIterator

import pytest

from magi.agent.run_control import RunControl, null_run_control
from magi.agent.task_agents.chat.contracts import (
    ChatRuntimeContext,
    IntentDecision,
)
from magi.agent.task_agents.chat.direct_handler import DirectLLMHandler
from magi.agent.task_agents.common.contracts import (
    DirectLLMRequest,
    ExecutionMode,
    IncomingFactKind,
    ToolSelection,
)
from magi.config.models import ThinkingDepth
from magi.llm.cancellable_client import CancellationRaised, RetractRaised
from magi.llm.streaming_events import LLMStreamEvent


class _RecordingCoordinator:
    """Captures every dispatch_stream_chunk call for assertion."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def dispatch_stream_chunk(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        is_final: bool,
        seq: int,
    ) -> None:
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "text": text,
                "is_final": is_final,
                "seq": seq,
            }
        )


class _ScriptedStreamPromptService:
    """PromptService stub that yields a fixed sequence of text_delta events."""

    def __init__(self, chunks: list[str], *, cancel_at: int | None = None) -> None:
        self._chunks = list(chunks)
        # If set, the stream raises CancellationRaised before yielding the
        # chunk at this index. Used to simulate mid-stream cancellation.
        self._cancel_at = cancel_at

    async def call_llm_stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        thinking_depth: ThinkingDepth | None = None,
        event_context: dict | None = None,
        control: RunControl | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        for i, chunk in enumerate(self._chunks):
            if self._cancel_at is not None and i == self._cancel_at:
                raise CancellationRaised("test:mid-stream")
            yield LLMStreamEvent(kind="text_delta", text=chunk)


def _minimal_context() -> ChatRuntimeContext:
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
        streaming_chat_enabled=True,
        core_model_supports_vision=True,
        control=null_run_control(),
    )


def _build_request() -> DirectLLMRequest:
    ctx = _minimal_context()
    intent = IntentDecision(
        intent="chat",
        execution_mode=ExecutionMode.DIRECT_LLM,
        difficulty="normal",
        tools=[],
    )
    return DirectLLMRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=ctx,
        intent=intent,
        tool_selection=ToolSelection(),
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        thinking_depth=ThinkingDepth.NONE,
    )


@pytest.mark.asyncio
async def test_direct_handler_dispatches_text_deltas_via_coordinator() -> None:
    """Each text_delta event becomes one coordinator.dispatch_stream_chunk
    call with monotonic ``seq``. After the stream finishes, the handler
    must dispatch one final ``is_final=True`` chunk."""
    coordinator = _RecordingCoordinator()
    prompt_service = _ScriptedStreamPromptService(["a", "b", "c"])
    handler = DirectLLMHandler(
        SimpleNamespace(prompt_service=prompt_service, coordinator=coordinator)
    )

    result = await handler.execute(_build_request())

    # The handler still returns its joined response_text.
    assert result.response_text == "abc"

    # 3 text_delta dispatches + 1 final boundary chunk = 4 calls total.
    assert len(coordinator.calls) == 4, coordinator.calls

    # Each delta call records the right text, is_final=False, monotonic seq.
    for i, expected_text in enumerate(["a", "b", "c"]):
        call = coordinator.calls[i]
        assert call["text"] == expected_text
        assert call["is_final"] is False
        assert call["seq"] == i
        assert call["session_id"] == "session-1"
        assert call["user_id"] == "user-1"

    final = coordinator.calls[-1]
    assert final["is_final"] is True
    assert final["text"] == ""
    assert final["seq"] == 3
    assert final["session_id"] == "session-1"
    assert final["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_direct_handler_dispatches_final_chunk_on_cancellation() -> None:
    """When the LLM stream raises CancellationRaised mid-way, the handler
    still emits the final ``is_final=True`` boundary chunk."""
    coordinator = _RecordingCoordinator()
    # Yield "a", "b", then raise before "c".
    prompt_service = _ScriptedStreamPromptService(["a", "b", "c"], cancel_at=2)
    handler = DirectLLMHandler(
        SimpleNamespace(prompt_service=prompt_service, coordinator=coordinator)
    )

    result = await handler.execute(_build_request())

    # First two deltas made it through, third did not.
    assert result.response_text == "ab"
    assert "abort_reason" in result.llm_trace
    assert result.llm_trace["abort_reason"].startswith("cancel:")

    # 2 delta dispatches + 1 final boundary chunk = 3 calls.
    assert len(coordinator.calls) == 3, coordinator.calls
    assert coordinator.calls[0]["text"] == "a"
    assert coordinator.calls[0]["seq"] == 0
    assert coordinator.calls[1]["text"] == "b"
    assert coordinator.calls[1]["seq"] == 1
    final = coordinator.calls[2]
    assert final["is_final"] is True
    assert final["text"] == ""
    assert final["seq"] == 2


@pytest.mark.asyncio
async def test_direct_handler_no_dispatch_when_coordinator_absent() -> None:
    """When deps.coordinator is None (legacy path), no exceptions are raised
    and the handler still produces its joined response_text."""
    prompt_service = _ScriptedStreamPromptService(["x", "y"])
    handler = DirectLLMHandler(
        SimpleNamespace(prompt_service=prompt_service, coordinator=None)
    )

    result = await handler.execute(_build_request())
    assert result.response_text == "xy"
