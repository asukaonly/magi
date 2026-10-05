from __future__ import annotations
import asyncio
import pytest
from dependency_injector import providers
from unittest.mock import AsyncMock, MagicMock, patch

from magi.core.container import Container, init_container
from magi.events.events import EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.events.tracing import (
    Span,
    TraceContext,
    current_span,
    current_trace_context,
    drain_pending,
    _resolve_event_bus,
    start_async_span,
    start_span,
)


def test_resolve_event_bus_uses_global_container_instance():
    container = init_container()
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    container.message_bus.override(providers.Object(bus))

    try:
        assert Container.message_bus() is not bus
        assert _resolve_event_bus() is bus
    finally:
        container.message_bus.reset_override()


@pytest.mark.parametrize("length", [4, 1000, 1001])
def test_span_exception_payload_preserves_error_and_reports_truncation(length):
    ctx = TraceContext(trace_id="t", span_id="s", parent_span_id=None)
    span = Span(node_type="span", name="x", context=ctx, started_at_ms=0)
    message = "x" * length
    span.record_exception(ValueError(message))
    payload = span._to_completed_payload(ended_at_ms=5)
    assert payload.status == "error"
    assert payload.error is not None
    assert payload.error.type == "ValueError"
    assert payload.error.message == message[:1000]
    assert payload.error.truncated is (length > 1000)


def test_span_to_completed_payload_fields():
    ctx = TraceContext(trace_id="trace-1", span_id="span-1", parent_span_id="parent-1")
    span = Span(node_type="tool_invocation", name="shell", context=ctx, started_at_ms=100)
    span.set_attribute("tool_name", "shell")
    span.set_attribute("a", 1)
    span.set_attribute("b", "two")
    span.set_attributes({"a": 2, "c": 3.0, "d": True})
    span.set_status("error")
    span.set_turn_id("turn-1")
    payload = span._to_completed_payload(ended_at_ms=250)
    assert payload.span_id == "span-1"
    assert payload.trace_id == "trace-1"
    assert payload.parent_span_id == "parent-1"
    assert payload.node_type == "tool_invocation"
    assert payload.name == "shell"
    assert payload.started_at_ms == 100
    assert payload.ended_at_ms == 250
    assert payload.duration_ms == 150
    assert payload.attributes == {"tool_name": "shell", "a": 2, "b": "two", "c": 3.0, "d": True}
    assert payload.status == "error"
    assert payload.turn_id == "turn-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["sync-context", "async-context", "awaited-delivery"])
@pytest.mark.parametrize("publisher", ["working", "missing", "failing"])
async def test_span_publication_observes_business_completion_and_restores_context(
    monkeypatch, entry, publisher
):
    from contextlib import AsyncExitStack
    from types import SimpleNamespace

    bus = SimpleNamespace(
        publish=AsyncMock(
            side_effect=RuntimeError("Bus unavailable") if publisher == "failing" else None,
            return_value=True,
        )
    )
    monkeypatch.setattr(
        "magi.events.tracing._resolve_event_bus", lambda: None if publisher == "missing" else bus
    )
    original_span = current_span()
    original_context = current_trace_context()
    steps = []
    async with AsyncExitStack() as stack:
        if entry == "sync-context":
            span = stack.enter_context(start_span(node_type="tool_invocation", name="shell"))
        else:
            span = await stack.enter_async_context(
                start_async_span(
                    node_type="tool_invocation",
                    name="shell",
                    delivery="sync" if entry == "awaited-delivery" else "async",
                )
            )
        assert current_span() is span
        assert current_trace_context() is span.context
        span.set_attribute("k", "v")
        steps.append("business-action")
    steps.append("after-span")
    assert current_span() is original_span
    assert current_trace_context() is original_context
    await drain_pending()
    steps.append("after-drain")
    assert steps == ["business-action", "after-span", "after-drain"]
    if publisher == "missing":
        bus.publish.assert_not_awaited()
    else:
        bus.publish.assert_awaited_once()
        event = bus.publish.await_args.args[0]
        assert event.type == EventTypes.SPAN_COMPLETED
        assert event.source == "tracing"
        assert event.data.span_id == span.span_id
        assert event.data.trace_id == span.trace_id
        assert event.data.node_type == "tool_invocation"
        assert event.data.name == "shell"
        assert event.data.attributes == {"k": "v"}


@pytest.mark.asyncio
async def test_start_async_span_delivery_sync_awaits_publish():
    fake_bus = MagicMock()
    publish_completed = asyncio.Event()

    async def slow_publish(_event):
        await asyncio.sleep(0.05)
        publish_completed.set()
        return True

    fake_bus.publish = slow_publish
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        async with start_async_span(node_type="span", delivery="sync"):
            pass
        assert publish_completed.is_set()


@pytest.mark.asyncio
async def test_cancellation_sets_status_cancelled():
    captured: list[SpanCompleted] = []
    fake_bus = MagicMock()

    async def capture(event):
        captured.append(event.data)
        return True

    fake_bus.publish = capture

    async def cancellable():
        with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
            async with start_async_span(node_type="span"):
                await asyncio.sleep(10)

    task = asyncio.create_task(cancellable())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await drain_pending()

    assert len(captured) == 1
    assert captured[0].status == "cancelled"


@pytest.mark.asyncio
async def test_exception_other_than_cancelled_records_exception():
    captured: list[SpanCompleted] = []
    fake_bus = MagicMock()

    async def capture(event):
        captured.append(event.data)
        return True

    fake_bus.publish = capture

    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        with pytest.raises(ValueError):
            async with start_async_span(node_type="span"):
                raise ValueError("kaboom")
        await drain_pending()

    assert len(captured) == 1
    assert captured[0].status == "error"
    assert captured[0].error is not None
    assert captured[0].error.type == "ValueError"


@pytest.mark.asyncio
@pytest.mark.parametrize("turn_id", [None, "turn-99"])
async def test_published_child_inherits_parent_turn_and_restores_parent_context(
    monkeypatch, turn_id
):
    bus = MagicMock(publish=AsyncMock(return_value=True))
    monkeypatch.setattr("magi.events.tracing._resolve_event_bus", lambda: bus)
    with start_span(node_type="span", name="parent") as parent:
        parent.set_turn_id(turn_id)
        with start_span(node_type="span", name="child") as child:
            assert current_span() is child
        assert current_span() is parent
    await drain_pending()
    assert bus.publish.await_count == 2
    events = {call.args[0].data.name: call.args[0].data for call in bus.publish.await_args_list}
    assert set(events) == {"parent", "child"}
    assert events["child"].turn_id == turn_id
    assert events["child"].parent_span_id == events["parent"].span_id
    assert events["child"].trace_id == events["parent"].trace_id
    assert events["child"].span_id != events["parent"].span_id


@pytest.mark.asyncio
async def test_drain_pending_awaits_inflight_publishes():
    fake_bus = MagicMock()
    finish_count = 0

    async def slow_publish(_event):
        nonlocal finish_count
        await asyncio.sleep(0.02)
        finish_count += 1
        return True

    fake_bus.publish = slow_publish
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        for _ in range(5):
            with start_span(node_type="span"):
                pass
        await drain_pending()
    assert finish_count == 5
