"""Phase 1 of D: LLMUsageSubscriber projects SpanCompleted(llm_call) → llm_usage."""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted, ToolError
from magi.llm.subscribers.llm_usage_subscriber import LLMUsageSubscriber


def _payload(*, node_type="llm_call", status="ok", error=None, attrs=None, turn_id=None):
    return SpanCompleted(
        span_id="span-1",
        trace_id="trace-1",
        parent_span_id=None,
        node_type=node_type,
        name="claude-opus-4",
        status=status,
        started_at_ms=1700000000000,
        ended_at_ms=1700000001500,
        duration_ms=1500,
        error=error,
        result_preview=None,
        turn_id=turn_id,
        attributes=attrs or {},
    )


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    bus.unsubscribe = AsyncMock(return_value=True)
    return bus


@pytest.fixture
def fake_store():
    s = MagicMock()
    s.record_call = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_subscribes_to_span_completed(fake_bus, fake_store):
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    fake_bus.subscribe.assert_awaited_once()
    assert fake_bus.subscribe.await_args.args[0] == EventTypes.SPAN_COMPLETED


@pytest.mark.asyncio
async def test_records_llm_call_with_full_payload(fake_bus, fake_store):
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(
        attrs={
            "request_id": "req-abc",
            "provider": "anthropic",
            "model": "claude-opus-4",
            "request_kind": "chat",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "usage_available": True,
            "session_id": "sess-1",
            "agent_id": "chat",
        },
        turn_id="turn-1",
    )
    await sub._on_event(Event(
        type=EventTypes.SPAN_COMPLETED, data=payload, event_id="evt-1", correlation_id="corr-1",
    ))
    await sub.drain()
    fake_store.record_call.assert_awaited_once()
    written = fake_store.record_call.await_args.args[0]
    assert written["request_id"] == "req-abc"
    assert written["provider"] == "anthropic"
    assert written["model"] == "claude-opus-4"
    assert written["request_kind"] == "chat"
    assert written["prompt_tokens"] == 100
    assert written["completion_tokens"] == 50
    assert written["total_tokens"] == 150
    assert written["usage_available"] is True
    assert written["latency_ms"] == 1500
    assert written["ttft_ms"] == 0       # not tracked today
    assert written["cost_usd"] == 0.0    # unknown model pricing
    assert written["success"] is True
    assert written["error"] is None
    assert written["correlation_id"] == "corr-1"
    assert written["session_id"] == "sess-1"
    assert written["turn_id"] == "turn-1"
    assert written["agent_id"] == "chat"
    assert written["created_at"] == 1700000000.0


@pytest.mark.asyncio
async def test_request_id_falls_back_to_span_id(fake_bus, fake_store):
    """When attributes['request_id'] is missing, span_id is used as fallback."""
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(attrs={"provider": "x", "model": "m", "request_kind": "chat"})
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()
    written = fake_store.record_call.await_args.args[0]
    assert written["request_id"] == "span-1"


@pytest.mark.asyncio
async def test_calculates_cost_from_registry_pricing(fake_bus, fake_store):
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(
        attrs={
            "provider": "openai",
            "model": "gpt-5",
            "request_kind": "chat",
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "cache_read_tokens": 200,
            "usage_available": True,
        },
    )
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()
    written = fake_store.record_call.await_args.args[0]
    assert written["cost_usd"] == pytest.approx(0.006025)


@pytest.mark.asyncio
async def test_correlation_id_falls_back_to_attributes(fake_bus, fake_store):
    """When event.correlation_id is None, attrs['correlation_id'] is used."""
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(attrs={
        "provider": "x", "model": "m", "request_kind": "chat",
        "correlation_id": "corr-from-attrs",
    })
    # Event has no correlation_id
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload, correlation_id=""))
    await sub.drain()
    written = fake_store.record_call.await_args.args[0]
    assert written["correlation_id"] == "corr-from-attrs"


@pytest.mark.asyncio
async def test_error_status_records_failure(fake_bus, fake_store):
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(
        status="error",
        error=ToolError(type="LLMError", message="rate limit"),
        attrs={"provider": "openai", "model": "gpt-4o", "request_kind": "chat"},
    )
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()
    written = fake_store.record_call.await_args.args[0]
    assert written["success"] is False
    assert written["error"] == "rate limit"


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", ["span", "tool_invocation", "intent_resolution", "turn", "task_lifecycle"])
async def test_skips_non_llm_call_node_types(fake_bus, fake_store, node_type):
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(node_type=node_type, attrs={"k": "v"})
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()
    fake_store.record_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_failure_does_not_break_subscriber(fake_bus, fake_store):
    fake_store.record_call.side_effect = RuntimeError("DB down")
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(attrs={"provider": "x", "model": "m", "request_kind": "chat"})
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()  # must not raise
    # subsequent event still processed
    fake_store.record_call.side_effect = None
    payload2 = _payload(attrs={"provider": "y", "model": "m2", "request_kind": "chat"})
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload2))
    await sub.drain()
    assert fake_store.record_call.await_count >= 2


@pytest.mark.asyncio
async def test_stop_unsubscribes_and_drains(fake_bus, fake_store):
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    await sub.stop()
    fake_bus.unsubscribe.assert_awaited_once()
