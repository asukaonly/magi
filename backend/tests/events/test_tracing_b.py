from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.events.tracing import (
    Span,
    TraceContext,
    current_span,
    current_trace_context,
    drain_pending,
    start_async_span,
    start_span,
)


def test_span_set_attribute_accumulates():
    ctx = TraceContext(trace_id="t", span_id="s", parent_span_id=None)
    span = Span(node_type="span", name="x", context=ctx, started_at_ms=0)
    span.set_attribute("a", 1)
    span.set_attribute("b", "two")
    span.set_attributes({"c": 3.0, "d": True})
    payload = span._to_completed_payload(ended_at_ms=10)
    assert payload.attributes == {"a": 1, "b": "two", "c": 3.0, "d": True}


def test_span_set_status():
    ctx = TraceContext(trace_id="t", span_id="s", parent_span_id=None)
    span = Span(node_type="span", name="x", context=ctx, started_at_ms=0)
    span.set_status("error")
    payload = span._to_completed_payload(ended_at_ms=5)
    assert payload.status == "error"


def test_span_record_exception_sets_error_and_status():
    ctx = TraceContext(trace_id="t", span_id="s", parent_span_id=None)
    span = Span(node_type="span", name="x", context=ctx, started_at_ms=0)
    span.record_exception(ValueError("boom"))
    payload = span._to_completed_payload(ended_at_ms=5)
    assert payload.status == "error"
    assert payload.error is not None
    assert payload.error.type == "ValueError"
    assert payload.error.message == "boom"


def test_span_set_turn_id():
    ctx = TraceContext(trace_id="t", span_id="s", parent_span_id=None)
    span = Span(node_type="span", name="x", context=ctx, started_at_ms=0)
    span.set_turn_id("turn-1")
    payload = span._to_completed_payload(ended_at_ms=5)
    assert payload.turn_id == "turn-1"


def test_span_to_completed_payload_fields():
    ctx = TraceContext(trace_id="trace-1", span_id="span-1", parent_span_id="parent-1")
    span = Span(node_type="tool_invocation", name="shell", context=ctx, started_at_ms=100)
    span.set_attribute("tool_name", "shell")
    payload = span._to_completed_payload(ended_at_ms=250)
    assert payload.span_id == "span-1"
    assert payload.trace_id == "trace-1"
    assert payload.parent_span_id == "parent-1"
    assert payload.node_type == "tool_invocation"
    assert payload.name == "shell"
    assert payload.started_at_ms == 100
    assert payload.ended_at_ms == 250
    assert payload.duration_ms == 150
    assert payload.attributes["tool_name"] == "shell"


def test_start_span_with_node_type_and_name():
    with start_span(node_type="tool_invocation", name="shell") as span:
        assert span.node_type == "tool_invocation"
        assert current_span() is span
        assert current_trace_context() is span.context


def test_start_span_publishes_on_exit_when_bus_wired():
    fake_bus = MagicMock()
    fake_bus.publish = AsyncMock(return_value=True)

    async def runner():
        with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
            with start_span(node_type="span", name="x") as span:
                span.set_attribute("k", "v")
            await drain_pending()

    asyncio.run(runner())
    fake_bus.publish.assert_awaited()
    event: Event = fake_bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    assert event.data.attributes == {"k": "v"}


def test_publish_failure_does_not_break_business_code():
    fake_bus = MagicMock()
    fake_bus.publish = AsyncMock(side_effect=RuntimeError("bus dead"))

    async def runner():
        with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
            with start_span(node_type="span") as span:
                span.set_attribute("k", "v")
            await drain_pending()

    asyncio.run(runner())


def test_start_span_no_bus_silently_skips():
    async def runner():
        with patch("magi.events.tracing._resolve_event_bus", return_value=None):
            with start_span(node_type="span"):
                pass
            await drain_pending()

    asyncio.run(runner())


@pytest.mark.asyncio
async def test_start_async_span_basic():
    async with start_async_span(node_type="task_lifecycle", name="task-1") as span:
        assert span.node_type == "task_lifecycle"
        assert current_span() is span


@pytest.mark.asyncio
async def test_start_async_span_publishes_on_exit():
    fake_bus = MagicMock()
    fake_bus.publish = AsyncMock(return_value=True)
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        async with start_async_span(node_type="task_lifecycle", name="t") as span:
            span.set_attribute("task_id", "orch-1")
        await drain_pending()
    fake_bus.publish.assert_awaited()
    payload = fake_bus.publish.await_args.args[0].data
    assert payload.node_type == "task_lifecycle"
    assert payload.attributes["task_id"] == "orch-1"


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


def test_nested_span_inherits_turn_id_from_parent():
    with start_span(node_type="span") as parent:
        parent.set_turn_id("turn-99")
        with start_span(node_type="span") as child:
            payload = child._to_completed_payload(ended_at_ms=1)
    assert payload.turn_id == "turn-99"


def test_nested_span_without_parent_turn_id_is_none():
    with start_span(node_type="span") as parent:
        with start_span(node_type="span") as child:
            payload = child._to_completed_payload(ended_at_ms=1)
    assert payload.turn_id is None


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
