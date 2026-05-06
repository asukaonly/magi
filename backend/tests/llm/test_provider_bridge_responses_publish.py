"""Phase 3 of D: provider_bridge.responses publishes SpanCompleted instead of LLM_CALL_COMPLETED."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted


def _build_handler():
    """Construct a minimal _emit_usage_event-callable harness."""
    from magi.llm.provider_bridge.responses import ProviderBridgeResponseMixin

    class Handler(ProviderBridgeResponseMixin):
        llm = MagicMock(model_name="claude-opus-4-7")
        _usage_event_publisher = None

        def _provider_name(self) -> str:
            return "anthropic"

    return Handler()


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    return bus


@pytest.mark.asyncio
async def test_publishes_span_completed_with_llm_call_node_type(fake_bus):
    handler = _build_handler()
    with patch("magi.runtime_trace.span_publisher.resolve_event_bus", return_value=fake_bus):
        await handler._emit_usage_event(
            success=True,
            latency_ms=1500,
            usage=MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            event_context={
                "request_id": "req-abc",
                "request_kind": "chat",
                "correlation_id": "corr-1",
                "session_id": "sess-1",
                "turn_id": "turn-1",
                "trace_id": "trace:turn-1",
                "parent_span_id": "turn-1:turn",
                "agent_id": "chat",
            },
            error=None,
        )
    fake_bus.publish.assert_awaited_once()
    event: Event = fake_bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    payload: SpanCompleted = event.data
    assert payload.node_type == "llm_call"
    assert payload.name == "claude-opus-4-7"
    assert payload.status == "ok"
    assert payload.duration_ms == 1500
    assert payload.turn_id == "turn-1"
    assert payload.trace_id == "trace:turn-1"
    assert payload.parent_span_id == "turn-1:turn"
    attrs = payload.attributes
    assert attrs["request_id"] == "req-abc"
    assert attrs["provider"] == "anthropic"
    assert attrs["request_kind"] == "chat"
    assert attrs["prompt_tokens"] == 100
    assert attrs["completion_tokens"] == 50
    assert attrs["input_tokens"] == 100
    assert attrs["output_tokens"] == 50
    assert attrs["total_tokens"] == 150
    assert attrs["usage_available"] is True
    assert attrs["session_id"] == "sess-1"
    assert attrs["agent_id"] == "chat"
    assert attrs["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_publishes_error_status_on_failure(fake_bus):
    handler = _build_handler()
    with patch("magi.runtime_trace.span_publisher.resolve_event_bus", return_value=fake_bus):
        await handler._emit_usage_event(
            success=False,
            latency_ms=500,
            usage=None,
            event_context={"request_kind": "chat"},
            error="rate limit",
        )
    payload: SpanCompleted = fake_bus.publish.await_args.args[0].data
    assert payload.status == "error"
    assert payload.error is not None
    assert payload.error.message == "rate limit"
    assert payload.attributes["usage_available"] is False
    assert payload.attributes["prompt_tokens"] == 0
    assert payload.attributes["total_tokens"] == 0


@pytest.mark.asyncio
async def test_inherits_trace_context_from_parent_span(fake_bus):
    """When called inside a parent span, LLM SpanCompleted gets parent's trace_id."""
    from magi.events.tracing import start_async_span
    handler = _build_handler()
    # Patch both resolve helpers so parent span and llm span both publish to fake_bus
    with patch("magi.runtime_trace.span_publisher.resolve_event_bus", return_value=fake_bus), \
         patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        async with start_async_span(node_type="span", name="parent") as parent_span:
            parent_trace_id = parent_span.trace_id
            parent_span_id = parent_span.span_id
            await handler._emit_usage_event(
                success=True,
                latency_ms=100,
                usage=None,
                event_context={
                    "request_kind": "chat",
                    "trace_id": "trace:event-context",
                    "parent_span_id": "event-parent",
                },
                error=None,
            )
    llm_events = [
        c.args[0] for c in fake_bus.publish.await_args_list
        if c.args[0].data.node_type == "llm_call"
    ]
    assert len(llm_events) == 1
    payload: SpanCompleted = llm_events[0].data
    assert payload.trace_id == parent_trace_id
    assert payload.parent_span_id == parent_span_id
