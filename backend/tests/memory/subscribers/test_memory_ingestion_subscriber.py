from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.chat.projector import ChatProjector
from magi.memory.subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber
from magi.events.events import (
    Event,
    EventTypes,
    PUBLISHED_MEMORY_EPOCH_METADATA_KEY,
)
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.events.domain_payloads import (
    ToolInvocationCompleted,
    TaskContext,
    UserMessageReceived,
)
from magi.memory.operation_barrier import AsyncOperationBarrier


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    bus.unsubscribe = AsyncMock(return_value=True)
    return bus


def _published_event(
    *,
    event_type: str,
    data,
    correlation_id: str | None = None,
) -> Event:
    return Event(
        type=event_type,
        data=data,
        correlation_id=correlation_id,
        metadata={PUBLISHED_MEMORY_EPOCH_METADATA_KEY: 0},
    )


@pytest.mark.asyncio
async def test_subscribes_to_all_canonical_event_types(fake_bus):
    unified = MagicMock()
    unified.memory_operation_epoch.return_value = 0
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()
    types_subscribed = [c.args[0] for c in fake_bus.subscribe.await_args_list]
    expected = {
        EventTypes.TOOL_INVOCATION_COMPLETED,
        EventTypes.SPAN_COMPLETED,
        EventTypes.USER_MESSAGE_RECEIVED,
        EventTypes.ASSISTANT_RESPONSE_PRODUCED,
        EventTypes.TASK_STARTED,
        EventTypes.TASK_COMPLETED,
        EventTypes.TASK_FAILED,
        EventTypes.SKILL_INVOCATION_COMPLETED,
    }
    assert set(types_subscribed) == expected


@pytest.mark.asyncio
async def test_translates_and_calls_ingest(fake_bus):
    unified = MagicMock()
    unified.memory_operation_epoch.return_value = 0
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()

    payload = ToolInvocationCompleted(
        tool_name="x",
        tool_category="external_tool",
        success=True,
        duration_ms=1.0,
        started_at=1.0,
        finished_at=2.0,
        args_summary=None,
        result_summary=None,
        error=None,
        context=TaskContext("s", "t", None, "u"),
    )
    await sub._on_event(
        _published_event(
            event_type=EventTypes.TOOL_INVOCATION_COMPLETED,
            data=payload,
            correlation_id="c",
        )
    )
    await sub.drain()

    unified.ingest_event.assert_awaited_once()
    me = unified.ingest_event.await_args.args[0]
    assert me.event_type == EventTypes.ACTION_EXECUTED
    assert me.source_item_id == "x"


@pytest.mark.asyncio
async def test_handler_returns_immediately_even_if_ingest_slow(fake_bus):
    unified = MagicMock()
    unified.memory_operation_epoch.return_value = 0

    async def slow_ingest(_me, *, expected_epoch):
        assert expected_epoch == 0
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
    await sub._on_event(_published_event(event_type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
    elapsed = loop.time() - start_t
    assert elapsed < 0.05  # handler did not await ingest

    await sub.drain()  # let inflight task finish for clean shutdown


@pytest.mark.asyncio
async def test_translation_returning_none_is_skipped(fake_bus):
    unified = MagicMock()
    unified.memory_operation_epoch.return_value = 0
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()

    await sub._on_event(_published_event(event_type="UnknownDomainEvent", data=None))
    await sub.drain()

    unified.ingest_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_failure_is_swallowed(fake_bus):
    unified = MagicMock()
    unified.memory_operation_epoch.return_value = 0
    unified.ingest_event = AsyncMock(side_effect=RuntimeError("ingest broke"))
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()

    payload = UserMessageReceived(content="hi", context=TaskContext("s", "t", None, "u"))
    await sub._on_event(_published_event(event_type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
    await sub.drain()  # must not raise


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_epoch", [None, True, -1, "0"])
async def test_missing_or_invalid_publication_epoch_is_rejected(
    fake_bus,
    invalid_epoch,
):
    unified = MagicMock()
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    payload = UserMessageReceived(
        content="must not be ingested",
        context=TaskContext("s", "t", None, "u"),
    )
    metadata = {} if invalid_epoch is None else {PUBLISHED_MEMORY_EPOCH_METADATA_KEY: invalid_epoch}

    await sub._on_event(
        Event(
            type=EventTypes.USER_MESSAGE_RECEIVED,
            data=payload,
            metadata=metadata,
        )
    )
    await sub.drain()

    unified.ingest_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_unsubscribes_and_drains(fake_bus):
    unified = MagicMock()
    unified.memory_operation_epoch.return_value = 0
    unified.ingest_event = AsyncMock()
    sub = MemoryIngestionSubscriber(event_bus=fake_bus, unified_memory=unified)
    await sub.start()
    await sub.stop()
    assert fake_bus.unsubscribe.await_count == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("projection_kind", ["user", "assistant"])
async def test_pre_clear_queued_chat_projection_is_dropped_and_new_projection_is_kept(
    projection_kind: str,
):
    class EpochMemory:
        def __init__(self) -> None:
            self.epoch = 0
            self.barrier = AsyncOperationBarrier()
            self.written: list[tuple[str, str, int]] = []

        def memory_operation_epoch(self) -> int:
            return self.epoch

        async def ingest_event(self, event, *, expected_epoch: int):
            async with self.barrier.operation():
                if expected_epoch != self.epoch:
                    return {"skipped": True}
                self.written.append((event.event_type, event.content, expected_epoch))
                return {"skipped": False}

    memory = EpochMemory()
    bus = InMemoryMessageBusBackend(
        num_workers=1,
        handler_timeout_seconds=5.0,
    )
    bus.bind_memory_operation_epoch(memory.memory_operation_epoch)
    sub = MemoryIngestionSubscriber(event_bus=bus, unified_memory=memory)
    projector = ChatProjector(event_bus=bus)
    blocker_started = asyncio.Event()
    blocker_release = asyncio.Event()

    async def _blocker(_event: Event) -> None:
        blocker_started.set()
        await blocker_release.wait()

    await bus.subscribe("BlockerEvent", _blocker)
    await sub.start()
    await bus.start()

    async def _project(*, message_id: str, turn_id: str, content: str) -> None:
        common = {
            "message_id": message_id,
            "user_id": "u",
            "session_id": "s",
            "turn_id": turn_id,
            "content": content,
            "created_at_ms": 1000,
        }
        if projection_kind == "user":
            await projector.project_user_message(**common)
        else:
            await projector.project_assistant_message(**common)

    try:
        assert await bus.publish(Event(type="BlockerEvent", data={}))
        await asyncio.wait_for(blocker_started.wait(), timeout=1.0)

        await _project(
            message_id="before-clear",
            turn_id="turn-before",
            content="private content before clear",
        )
        async with memory.barrier.exclusive():
            memory.epoch += 1
            blocker_release.set()
            await _project(
                message_id="after-clear",
                turn_id="turn-after",
                content="new content after clear",
            )

        assert bus._queue is not None
        await asyncio.wait_for(bus._queue.join(), timeout=1.0)
        await sub.drain()

        expected_type = (
            EventTypes.USER_MESSAGE if projection_kind == "user" else EventTypes.AI_RESPONSE
        )
        assert memory.written == [
            (expected_type, "new content after clear", 1),
        ]
    finally:
        blocker_release.set()
        await sub.stop()
        await bus.stop()
