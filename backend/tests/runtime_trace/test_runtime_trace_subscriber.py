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
from magi.runtime_trace.subscribers.runtime_trace_subscriber import (
    RuntimeTraceSubscriber,
)
from magi.runtime_trace.lifecycle import RuntimeTraceSubscriberModule
from magi.bootstrap.context import RuntimeBootstrapContext


def _make_payload(node_type="span", **kw):
    defaults = dict(
        span_id="s1",
        trace_id="t1",
        parent_span_id=None,
        node_type=node_type,
        name="x",
        status="ok",
        started_at_ms=100,
        ended_at_ms=200,
        duration_ms=100,
        error=None,
        result_preview=None,
        turn_id=None,
        attributes={},
    )
    defaults.update(kw)
    return SpanCompleted(**defaults)


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    bus.unsubscribe = AsyncMock(return_value=True)
    return bus


@pytest.fixture
def fake_store():
    s = MagicMock()
    s.upsert_span = AsyncMock()
    s.upsert_tool_call = AsyncMock()
    s.upsert_llm_call = AsyncMock()
    s.upsert_turn = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_default_node_type_writes_only_trace_spans(fake_bus, fake_store):
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    p = _make_payload(node_type="span")
    await sub._on_span_completed(Event(type=EventTypes.SPAN_COMPLETED, data=p))
    await sub.drain()
    fake_store.upsert_span.assert_awaited_once()
    fake_store.upsert_tool_call.assert_not_awaited()
    fake_store.upsert_llm_call.assert_not_awaited()
    fake_store.upsert_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_invocation_writes_span_and_tool_call(fake_bus, fake_store):
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    p = _make_payload(
        node_type="tool_invocation",
        name="shell",
        attributes={
            "tool_name": "shell",
            "arguments_json": '{"cmd":"ls"}',
            "success": True,
        },
    )
    await sub._on_span_completed(Event(type=EventTypes.SPAN_COMPLETED, data=p))
    await sub.drain()
    fake_store.upsert_span.assert_awaited_once()
    fake_store.upsert_tool_call.assert_awaited_once()
    rec = fake_store.upsert_tool_call.await_args.args[0]
    assert rec.tool_name == "shell"
    assert rec.success is True


@pytest.mark.asyncio
async def test_tool_invocation_parses_string_false_success(fake_bus, fake_store):
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    p = _make_payload(
        node_type="tool_invocation",
        name="shell",
        attributes={
            "tool_name": "shell",
            "arguments_json": '{"cmd":"false"}',
            "success": "false",
        },
    )
    await sub._on_span_completed(Event(type=EventTypes.SPAN_COMPLETED, data=p))
    await sub.drain()
    rec = fake_store.upsert_tool_call.await_args.args[0]
    assert rec.success is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage,expected",
    [
        ({"input_tokens": 100}, (100, 0)),
        ({"prompt_tokens": 120, "completion_tokens": 45}, (120, 45)),
        (
            {"input_tokens": 0, "output_tokens": 12, "prompt_tokens": 120, "completion_tokens": 45},
            (0, 12),
        ),
    ],
)
async def test_registered_llm_handler_preserves_identity_and_token_precedence(
    fake_bus, fake_store, usage, expected
):
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    fake_bus.subscribe.assert_awaited_once_with(EventTypes.SPAN_COMPLETED, sub._on_span_completed)
    handler = fake_bus.subscribe.await_args.args[1]
    payload = _make_payload(
        node_type="llm_call",
        span_id="llm-span",
        trace_id="trace-1",
        turn_id="turn-1",
        name="model-1",
        attributes={"provider": "provider-1", "model": "model-1", **usage},
    )
    await handler(Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.stop()
    fake_store.upsert_span.assert_awaited_once()
    fake_store.upsert_llm_call.assert_awaited_once()
    record = fake_store.upsert_llm_call.await_args.args[0]
    assert (record.span_id, record.trace_id, record.turn_id, record.provider, record.model) == (
        "llm-span",
        "trace-1",
        "turn-1",
        "provider-1",
        "model-1",
    )
    assert (record.input_tokens, record.output_tokens) == expected
    fake_store.upsert_tool_call.assert_not_awaited()
    fake_store.upsert_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_turn_dispatch_preserves_complete_owner_and_status_record(fake_bus, fake_store):
    from magi.runtime_trace.contracts import TraceTurnRecord

    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    payload = _make_payload(
        node_type="turn_record",
        trace_id="trace-owner",
        turn_id="fallback-turn",
        attributes={
            "turn_id": "turn-owner",
            "session_id": "session-owner",
            "user_id": "user-owner",
            "status": "completed",
            "mode": "chat",
            "started_at_ms": 1000,
            "ended_at_ms": 2400,
            "duration_ms": 1400,
            "user_message_preview": "question",
            "response_preview": "answer",
            "run_id": "run-1",
            "run_revision": 2,
            "created_at_ms": 900,
            "updated_at_ms": 2500,
        },
    )
    await fake_bus.subscribe.await_args.args[1](Event(type=EventTypes.SPAN_COMPLETED, data=payload))
    await sub.stop()
    fake_store.upsert_turn.assert_awaited_once_with(
        TraceTurnRecord(
            trace_id="trace-owner",
            turn_id="turn-owner",
            session_id="session-owner",
            user_id="user-owner",
            status="completed",
            mode="chat",
            started_at_ms=1000,
            ended_at_ms=2400,
            duration_ms=1400,
            user_message_preview="question",
            response_preview="answer",
            run_id="run-1",
            run_revision=2,
            created_at_ms=900,
            updated_at_ms=2500,
        )
    )
    fake_store.upsert_span.assert_not_awaited()
    fake_store.upsert_tool_call.assert_not_awaited()
    fake_store.upsert_llm_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_specialized_write_does_not_drop_the_next_distinct_span(fake_bus, fake_store):
    fake_store.upsert_tool_call.side_effect = RuntimeError("DB down")
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    handler = fake_bus.subscribe.await_args.args[1]
    await handler(
        Event(
            type=EventTypes.SPAN_COMPLETED,
            data=_make_payload(
                node_type="tool_invocation",
                span_id="failed-tool",
                attributes={"tool_name": "shell"},
            ),
        )
    )
    await handler(
        Event(
            type=EventTypes.SPAN_COMPLETED,
            data=_make_payload(node_type="span", span_id="following-span"),
        )
    )
    await sub.stop()
    fake_store.upsert_tool_call.assert_awaited_once()
    assert fake_store.upsert_tool_call.await_args.args[0].span_id == "failed-tool"
    assert [call.args[0].span_id for call in fake_store.upsert_span.await_args_list] == [
        "failed-tool",
        "following-span",
    ]


@pytest.mark.asyncio
async def test_stop_unsubscribes_before_waiting_for_the_inflight_write(fake_bus, fake_store):
    started = asyncio.Event()
    release = asyncio.Event()
    unsubscribed = asyncio.Event()
    written = []

    async def write(record):
        started.set()
        await release.wait()
        written.append(record.span_id)

    async def unsubscribe(subscription_id):
        assert subscription_id == "sub-id"
        unsubscribed.set()

    fake_store.upsert_span.side_effect = write
    fake_bus.unsubscribe.side_effect = unsubscribe
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    await fake_bus.subscribe.await_args.args[1](
        Event(type=EventTypes.SPAN_COMPLETED, data=_make_payload(span_id="pending-span"))
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    stopping = asyncio.create_task(sub.stop())
    try:
        await asyncio.wait_for(unsubscribed.wait(), timeout=1)
        assert not stopping.done()
        assert written == []
    finally:
        release.set()
        await asyncio.wait_for(stopping, timeout=1)
    assert written == ["pending-span"]
    fake_bus.unsubscribe.assert_awaited_once_with("sub-id")


@pytest.mark.asyncio
async def test_error_payload_propagates_to_span_record(fake_bus, fake_store):
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    p = _make_payload(
        status="error",
        error=ToolError(type="ValueError", message="boom"),
    )
    await sub._on_span_completed(Event(type=EventTypes.SPAN_COMPLETED, data=p))
    await sub.drain()
    rec = fake_store.upsert_span.await_args.args[0]
    assert rec.status == "error"
    assert rec.error_text == "boom"


@pytest.mark.asyncio
async def test_span_preview_attributes_propagate_to_span_record(fake_bus, fake_store):
    sub = RuntimeTraceSubscriber(event_bus=fake_bus, trace_store=fake_store)
    await sub.start()
    p = _make_payload(
        attributes={
            "input_preview": "User input preview",
            "output_preview": "Model output preview",
        },
    )
    await sub._on_span_completed(Event(type=EventTypes.SPAN_COMPLETED, data=p))
    await sub.drain()

    rec = fake_store.upsert_span.await_args.args[0]
    assert rec.input_preview == "User input preview"
    assert rec.output_preview == "Model output preview"


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
    seen_span_ids: list[str] = []

    async def record_span(record):
        seen_span_ids.append(record.span_id)
        if record.span_id == "started-before-clear":
            projection_started.set()
            await allow_projection.wait()

    fake_store.upsert_span.side_effect = record_span
    sub = RuntimeTraceSubscriber(
        event_bus=fake_bus,
        trace_store=fake_store,
        memory_epoch_getter=lambda: epoch,
    )
    await sub.start()

    def event(
        span_id: str,
        *,
        published_epoch: int,
        started_at_ms: int = 100,
    ) -> Event:
        return Event(
            type=EventTypes.SPAN_COMPLETED,
            data=_make_payload(
                span_id=span_id,
                started_at_ms=started_at_ms,
                ended_at_ms=started_at_ms + 100,
            ),
            metadata={PUBLISHED_MEMORY_EPOCH_METADATA_KEY: published_epoch},
        )

    await sub._on_span_completed(event("started-before-clear", published_epoch=0))
    await projection_started.wait()
    await sub._on_span_completed(event("queued-before-clear", published_epoch=0))

    async def hold_clear_boundary() -> None:
        nonlocal epoch
        async with sub.user_content_clear_boundary():
            epoch = 1
            clear_entered.set()
            await allow_clear_exit.wait()

    clear_task = asyncio.create_task(hold_clear_boundary())
    await asyncio.sleep(0)
    assert clear_entered.is_set() is False

    allow_projection.set()
    await clear_entered.wait()
    await sub._on_span_completed(event("during-clear", published_epoch=1))
    allow_clear_exit.set()
    await clear_task
    await sub.drain()

    await sub._on_span_completed(event("old-after-clear", published_epoch=0))
    cutoff = sub._clear_cutoff_started_at_ms
    await sub._on_span_completed(
        event(
            "late-old-after-clear",
            published_epoch=1,
            started_at_ms=cutoff,
        )
    )
    await sub._on_span_completed(
        event(
            "new-after-clear",
            published_epoch=1,
            started_at_ms=cutoff + 1,
        )
    )
    await sub.drain()

    assert seen_span_ids == ["started-before-clear", "new-after-clear"]


@pytest.mark.asyncio
async def test_lifecycle_exposes_and_releases_clearable_subscriber(
    fake_bus,
    fake_store,
):
    context = RuntimeBootstrapContext()
    context.message_bus.message_bus = fake_bus
    context.runtime_trace.store = fake_store
    memory = MagicMock()
    memory.memory_operation_epoch.return_value = 0
    context.memory.unified_memory = memory

    module = RuntimeTraceSubscriberModule(context)
    await module.init()

    assert context.runtime_trace.subscriber is not None
    fake_bus.subscribe.assert_awaited_once()

    await module.shutdown()

    assert context.runtime_trace.subscriber is None
    fake_bus.unsubscribe.assert_awaited_once()
