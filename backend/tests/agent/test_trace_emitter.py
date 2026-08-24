from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.agent.trace.contracts import (
    TRACE_NODE_COMPLETED_EVENT_TYPE,
    TRACE_NODE_STARTED_EVENT_TYPE,
    TraceNodePayload,
)
from magi.agent.trace.emitter import TraceEventEmitter
from magi.agent.trace.time import build_trace_timing


def test_build_trace_timing_uses_monotonic_delta_for_duration_ms() -> None:
    timing = build_trace_timing(
        started_at_ms=1710751000123,
        ended_at_ms=1710751001123,
        started_monotonic=10.0,
        ended_monotonic=11.125,
    )

    assert timing.started_at_ms == 1710751000123
    assert timing.ended_at_ms == 1710751001123
    assert timing.duration_ms == 1125


def test_trace_node_payload_serializes_common_trace_fields() -> None:
    payload = TraceNodePayload(
        trace_id="trace_turn_1",
        turn_id="turn_1",
        span_id="span_1",
        parent_span_id="root_1",
        node_type="llm_call",
        name="Main response generation",
        status="completed",
        attempt_index=1,
        retry_count=0,
        started_at_ms=1710751000123,
        ended_at_ms=1710751001456,
        duration_ms=1333,
        input={"messages": 4},
        output={"finish_reason": "stop"},
        metrics={"input_tokens": 12, "output_tokens": 8},
        error=None,
        tags={"user_id": "local_user", "session_id": "session_1"},
    )

    serialized = payload.to_event_payload()

    assert serialized["trace_id"] == "trace_turn_1"
    assert serialized["turn_id"] == "turn_1"
    assert serialized["node_type"] == "llm_call"
    assert serialized["duration_ms"] == 1333
    assert serialized["metrics"]["input_tokens"] == 12
    assert serialized["tags"]["session_id"] == "session_1"


@pytest.mark.asyncio
async def test_trace_event_emitter_emits_started_and_completed_runtime_events() -> None:
    runtime_event = AsyncMock()
    emitter = TraceEventEmitter(emit_runtime_event=runtime_event)

    await emitter.emit_node_started(
        trace_id="trace_turn_1",
        turn_id="turn_1",
        span_id="span_1",
        parent_span_id=None,
        node_type="turn",
        name="Chat turn",
        user_id="local_user",
        session_id="session_1",
        started_at_ms=1710751000123,
    )
    await emitter.emit_node_completed(
        trace_id="trace_turn_1",
        turn_id="turn_1",
        span_id="span_2",
        parent_span_id="span_1",
        node_type="capability_resolution",
        name="Capability resolution",
        user_id="local_user",
        session_id="session_1",
        started_at_ms=1710751000123,
        ended_at_ms=1710751000205,
        duration_ms=82,
        output={"selected_tools": []},
    )

    assert runtime_event.await_count == 2
    first_call = runtime_event.await_args_list[0].kwargs
    second_call = runtime_event.await_args_list[1].kwargs

    assert first_call["event_type"] == TRACE_NODE_STARTED_EVENT_TYPE
    assert first_call["payload"]["status"] == "running"
    assert first_call["payload"]["node_type"] == "turn"

    assert second_call["event_type"] == TRACE_NODE_COMPLETED_EVENT_TYPE
    assert second_call["payload"]["status"] == "completed"
    assert second_call["payload"]["output"]["selected_tools"] == []
    assert second_call["payload"]["duration_ms"] == 82
