from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.memory.subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    ToolInvocationCompleted, TaskContext, UserMessageReceived,
)


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    bus.unsubscribe = AsyncMock(return_value=True)
    return bus


@pytest.mark.asyncio
async def test_subscribes_to_all_seven_event_types(fake_bus):
    unified = MagicMock()
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()
    types_subscribed = [c.args[0] for c in fake_bus.subscribe.await_args_list]
    expected = {
        EventTypes.TOOL_INVOCATION_COMPLETED,
        EventTypes.USER_MESSAGE_RECEIVED,
        EventTypes.ASSISTANT_RESPONSE_PRODUCED,
        EventTypes.SENSOR_EVENT_EMITTED,
        EventTypes.TASK_STARTED,
        EventTypes.TASK_COMPLETED,
        EventTypes.TASK_FAILED,
    }
    assert set(types_subscribed) == expected


@pytest.mark.asyncio
async def test_translates_and_calls_ingest(fake_bus):
    unified = MagicMock()
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()

    payload = ToolInvocationCompleted(
        tool_name="x", tool_category="external_tool",
        success=True, duration_ms=1.0,
        started_at=1.0, finished_at=2.0,
        args_summary=None, result_summary=None, error=None,
        context=TaskContext("s", "t", None, "u"),
    )
    await sub._on_event(Event(
        type=EventTypes.TOOL_INVOCATION_COMPLETED,
        data=payload,
        correlation_id="c",
    ))
    await sub.drain()

    unified.ingest_event.assert_awaited_once()
    me = unified.ingest_event.await_args.args[0]
    assert me.event_type == EventTypes.ACTION_EXECUTED
    assert me.source_item_id == "x"


@pytest.mark.asyncio
async def test_handler_returns_immediately_even_if_ingest_slow(fake_bus):
    unified = MagicMock()

    async def slow_ingest(_me):
        await asyncio.sleep(0.2)

    unified.ingest_event = slow_ingest
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()

    payload = UserMessageReceived(
        content="hi",
        context=TaskContext("s", "t", None, "u"),
    )
    loop = asyncio.get_event_loop()
    start_t = loop.time()
    await sub._on_event(Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
    elapsed = loop.time() - start_t
    assert elapsed < 0.05  # handler did not await ingest

    await sub.drain()  # let inflight task finish for clean shutdown


@pytest.mark.asyncio
async def test_translation_returning_none_is_skipped(fake_bus):
    unified = MagicMock()
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()

    await sub._on_event(Event(type="UnknownDomainEvent", data=None))
    await sub.drain()

    unified.ingest_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_failure_is_swallowed(fake_bus):
    unified = MagicMock()
    unified.ingest_event = AsyncMock(side_effect=RuntimeError("ingest broke"))
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()

    payload = UserMessageReceived(
        content="hi", context=TaskContext("s", "t", None, "u"))
    await sub._on_event(Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
    await sub.drain()  # must not raise


@pytest.mark.asyncio
async def test_stop_unsubscribes_and_drains(fake_bus):
    unified = MagicMock()
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()
    await sub.stop()
    assert fake_bus.unsubscribe.await_count == 7
