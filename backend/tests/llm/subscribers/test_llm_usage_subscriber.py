"""Phase 1 of D: LLMUsageSubscriber projects SpanCompleted(llm_call) → llm_usage."""
from __future__ import annotations
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import (
    Event,
    EventTypes,
    PUBLISHED_MEMORY_EPOCH_METADATA_KEY,
)
from magi.events.domain_payloads import SpanCompleted, ToolError
from magi.llm.subscribers.llm_usage_subscriber import LLMUsageSubscriber


def _payload(
    *,
    node_type="llm_call",
    status="ok",
    error=None,
    attrs=None,
    turn_id=None,
    started_at_ms=1700000000000,
):
    return SpanCompleted(
        span_id="span-1",
        trace_id="trace-1",
        parent_span_id=None,
        node_type=node_type,
        name="claude-opus-4",
        status=status,
        started_at_ms=started_at_ms,
        ended_at_ms=started_at_ms + 1500,
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
    s.record_cache_observation = AsyncMock()
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
            "cache_read_tokens": 70,
            "cache_write_tokens": 12,
            "cache_write_1h_tokens": 5,
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
    assert written["cache_read_tokens"] == 70
    assert written["cache_write_tokens"] == 12
    assert written["cache_write_1h_tokens"] == 5
    assert written["usage_available"] is True
    assert written["latency_ms"] == 1500
    assert written["ttft_ms"] == 0       # not tracked today
    assert written["cost_usd"] is None       # unknown model -> no pricing data
    assert written["cost_currency"] is None  # NULL currency = "no pricing data" sentinel
    assert written["success"] is True
    assert written["error"] is None
    assert written["correlation_id"] == "corr-1"
    assert written["session_id"] == "sess-1"
    assert written["turn_id"] == "turn-1"
    assert written["agent_id"] == "chat"
    assert written["created_at"] == 1700000000.0


@pytest.mark.asyncio
async def test_records_cache_observation_when_span_contains_diagnostics(fake_bus, fake_store):
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(
        attrs={
            "request_id": "req-cache",
            "provider": "openai",
            "model": "gpt-5",
            "request_kind": "function_calling:chat_tools",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cache_read_tokens": 70,
            "cache_write_tokens": 5,
            "cache_write_1h_tokens": 0,
            "cache_fields_seen": True,
            "session_id": "sess-1",
            "agent_id": "chat",
            "cache_observation": {
                "cache_strategy": "prompt_cache_key",
                "cache_eligible": True,
                "system_head_hash": "head",
                "system_head_chars": 1000,
                "dynamic_context_hash": "tail",
                "dynamic_context_chars": 200,
                "tools_hash": "tools",
                "tool_count": 2,
                "tool_names": ["weather", "web-search"],
            },
        },
        turn_id="turn-1",
    )

    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()

    fake_store.record_cache_observation.assert_awaited_once()
    written = fake_store.record_cache_observation.await_args.args[0]
    assert written["request_id"] == "req-cache"
    assert written["provider"] == "openai"
    assert written["model"] == "gpt-5"
    assert written["request_kind"] == "function_calling:chat_tools"
    assert written["cache_strategy"] == "prompt_cache_key"
    assert written["system_head_hash"] == "head"
    assert written["tool_names"] == ["weather", "web-search"]
    assert written["cache_fields_seen"] is True
    assert written["cache_read_tokens"] == 70
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
    assert written["cost_currency"] == "USD"


@pytest.mark.asyncio
async def test_records_native_currency_for_non_usd_model(fake_bus, fake_store):
    """Non-USD (e.g. CNY) pricing must be recorded, not silently dropped to 0."""
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(
        attrs={
            "provider": "dashscope",
            "model": "qwen3.6-plus",  # priced in CNY in the shipped registry
            "request_kind": "chat",
            "prompt_tokens": 1_000_000,
            "completion_tokens": 0,
            "usage_available": True,
        },
    )
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()
    written = fake_store.record_call.await_args.args[0]
    # qwen3.6-plus input is 2.0 CNY / million tokens -> 1M prompt tokens = 2.0 CNY
    assert written["cost_currency"] == "CNY"
    assert written["cost_usd"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_embedding_cost_fallback_when_not_a_chat_model(fake_bus, fake_store):
    """Embedding models aren't chat models, so the chat calc returns None and the
    embedding-fallback prices the request in the model's native currency."""
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(
        attrs={
            "provider": "dashscope",
            "model": "text-embedding-v3",  # CNY 0.5 / million tokens, input-only
            "request_kind": "embedding",
            "prompt_tokens": 1_000_000,
            "completion_tokens": 0,
            "total_tokens": 1_000_000,
            "usage_available": True,
        },
    )
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()
    written = fake_store.record_call.await_args.args[0]
    assert written["request_kind"] == "embedding"
    assert written["cost_currency"] == "CNY"
    assert written["cost_usd"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_image_generation_cost_fallback(fake_bus, fake_store):
    """Image-generation models are priced per image, so chat/embedding calcs
    return None and the image-fallback prices it in the model's native currency."""
    sub = LLMUsageSubscriber(event_bus=fake_bus, llm_usage_store=fake_store)
    await sub.start()
    payload = _payload(
        attrs={
            "provider": "dashscope",
            "model": "qwen-image-2.0-pro",  # CNY 0.5 / image
            "request_kind": "image_generation",
            "image_count": 2,
            "usage_available": True,
        },
    )
    await sub._on_event(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.drain()
    written = fake_store.record_call.await_args.args[0]
    assert written["request_kind"] == "image_generation"
    assert written["cost_currency"] == "CNY"
    assert written["cost_usd"] == pytest.approx(1.0)


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
@pytest.mark.parametrize("node_type", ["span", "tool_invocation", "capability_resolution", "turn", "task_lifecycle"])
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


@pytest.mark.asyncio
async def test_clear_boundary_drains_started_projection_and_rejects_old_work(
    fake_bus,
    fake_store,
):
    epoch = 0
    projection_started = asyncio.Event()
    allow_projection = asyncio.Event()
    clear_entered = asyncio.Event()
    allow_clear_exit = asyncio.Event()
    seen_request_ids: list[str] = []

    async def record_call(payload):
        request_id = str(payload["request_id"])
        seen_request_ids.append(request_id)
        if request_id == "started-before-clear":
            projection_started.set()
            await allow_projection.wait()

    fake_store.record_call.side_effect = record_call
    sub = LLMUsageSubscriber(
        event_bus=fake_bus,
        llm_usage_store=fake_store,
        memory_epoch_getter=lambda: epoch,
    )
    await sub.start()

    def event(
        request_id: str,
        *,
        published_epoch: int,
        started_at_ms: int = 1700000000000,
    ) -> Event:
        return Event(
            type=EventTypes.SPAN_COMPLETED,
            data=_payload(
                attrs={"request_id": request_id},
                started_at_ms=started_at_ms,
            ),
            metadata={PUBLISHED_MEMORY_EPOCH_METADATA_KEY: published_epoch},
        )

    await sub._on_event(event("started-before-clear", published_epoch=0))
    await projection_started.wait()

    async def hold_clear_boundary() -> None:
        nonlocal epoch
        async with sub.user_content_clear_boundary():
            epoch = 1
            clear_entered.set()
            await allow_clear_exit.wait()

    clear_task = asyncio.create_task(hold_clear_boundary())
    await asyncio.sleep(0)
    assert clear_entered.is_set() is False

    await sub._on_event(event("while-clear-waits", published_epoch=0))
    allow_projection.set()
    await clear_entered.wait()
    await sub._on_event(event("during-clear", published_epoch=1))
    allow_clear_exit.set()
    await clear_task
    await sub.drain()

    await sub._on_event(event("old-after-clear", published_epoch=0))
    cutoff = sub._clear_cutoff_started_at_ms
    await sub._on_event(
        event(
            "late-old-after-clear",
            published_epoch=1,
            started_at_ms=cutoff,
        )
    )
    await sub._on_event(
        event(
            "new-after-clear",
            published_epoch=1,
            started_at_ms=cutoff + 1,
        )
    )
    await sub.drain()

    assert seen_request_ids == ["started-before-clear", "new-after-clear"]
