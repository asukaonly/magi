"""Phase G+1 Step 2: chunk write-path convergence.

The chat streaming sink (``ChatStreamingMixin._emit_stream_event`` /
``_build_stream_sink``) must route EVERY LLM stream event through
``coordinator.dispatch_stream_chunk`` — carrying the full ``LLMStreamEvent``
so ChatSseChannel.deliver_chunk can serialize every kind (tool_call /
reasoning / status / text_flush / text_delta) — rather than the legacy
notifier write path (removed in P3 Step 5).
"""
from __future__ import annotations

import pytest

from magi.chat.task_agent.streaming import ChatStreamingMixin
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
        turn_id: str | None = None,
        event=None,
        persona_id: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "text": text,
                "is_final": is_final,
                "seq": seq,
                "turn_id": turn_id,
                "event": event,
                "persona_id": persona_id,
            }
        )


class _ExplodingNotifier:
    """The legacy notifier path must NOT be called by the converged sink."""

    async def emit_stream_event(self, **_kwargs) -> None:  # pragma: no cover
        raise AssertionError(
            "emit_stream_event must not be called once the sink routes "
            "through coordinator.dispatch_stream_chunk"
        )


class _Agent(ChatStreamingMixin):
    def __init__(self, coordinator) -> None:
        self._coordinator = coordinator
        # A real notifier exists but must stay untouched by the chunk path.
        self._postprocess_service = type(
            "_PS", (), {"_runtime_notifier": _ExplodingNotifier()}
        )()


@pytest.mark.asyncio
async def test_emit_stream_event_dispatches_through_coordinator_with_event():
    coordinator = _RecordingCoordinator()
    agent = _Agent(coordinator)
    event = LLMStreamEvent(kind="reasoning_delta", text="thinking...")

    await agent._emit_stream_event(
        event=event,
        user_id="u1",
        session_id="s1",
        turn_id="t1",
        persona_id="p1",
        seq=5,
    )

    assert len(coordinator.calls) == 1
    call = coordinator.calls[0]
    assert call["event"] is event
    assert call["session_id"] == "s1"
    assert call["user_id"] == "u1"
    assert call["turn_id"] == "t1"
    assert call["persona_id"] == "p1"
    assert call["seq"] == 5
    assert call["is_final"] is False
    # text mirrors the event text so legacy/text-only channels still work.
    assert call["text"] == "thinking..."


@pytest.mark.asyncio
async def test_build_stream_sink_dispatches_each_event_with_monotonic_seq():
    coordinator = _RecordingCoordinator()
    agent = _Agent(coordinator)
    sink = agent._build_stream_sink(
        user_id="u1", session_id="s1", turn_id="t1", persona_id="p1",
    )

    await sink(LLMStreamEvent(kind="text_delta", text="he"))
    await sink(
        LLMStreamEvent(kind="tool_call_start", tool_call_id="tc1", tool_name="grep")
    )
    await sink(LLMStreamEvent(kind="text_delta", text="llo"))

    assert len(coordinator.calls) == 3
    assert [c["seq"] for c in coordinator.calls] == [0, 1, 2]
    assert [c["event"].kind for c in coordinator.calls] == [
        "text_delta",
        "tool_call_start",
        "text_delta",
    ]
    assert all(
        c["turn_id"] == "t1" and c["persona_id"] == "p1"
        for c in coordinator.calls
    )
