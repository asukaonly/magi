from __future__ import annotations

import asyncio

import pytest

from magi.events.events import (
    Event,
    EventTypes,
    PUBLISHED_MEMORY_EPOCH_METADATA_KEY,
    PropagationMode,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)
from magi.events.in_memory_backend import InMemoryMessageBusBackend


@pytest.mark.asyncio
async def test_publish_requires_local_subscriber_for_critical_events() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    await backend.start()
    try:
        published = await backend.publish(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"response": "hello"},
                metadata={REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True},
            )
        )

        assert published is False
        stats = await backend.get_stats()
        assert stats["published_count"] == 0
        assert stats["dropped_count"] == 1
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_publish_delivers_noncritical_events_to_local_subscribers() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    received: list[int] = []

    async def _handler(event: Event) -> None:
        received.append(int(event.data["value"]))

    await backend.subscribe("NonCriticalEvent", _handler)
    await backend.start()
    try:
        published = await backend.publish(
            Event(
                type="NonCriticalEvent",
                data={"value": 1},
            )
        )

        assert published is True
        await asyncio.sleep(0.05)
        assert received == [1]
        stats = await backend.get_stats()
        assert stats["processed_count"] == 1
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_competing_subscribers_deliver_to_only_one_handler() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    received: list[str] = []

    async def _first(event: Event) -> None:
        received.append(f"first:{event.type}")

    async def _second(event: Event) -> None:
        received.append(f"second:{event.type}")

    await backend.subscribe("CompetingEvent", _first, propagation_mode=PropagationMode.COMPETING)
    await backend.subscribe("CompetingEvent", _second, propagation_mode=PropagationMode.COMPETING)
    await backend.start()
    try:
        published = await backend.publish(Event(type="CompetingEvent", data={"value": 1}))

        assert published is True
        await asyncio.sleep(0.05)
        assert len(received) == 1
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_stop_waits_for_processing_handlers_to_finish() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    started = asyncio.Event()
    release = asyncio.Event()
    finished: list[str] = []

    async def _handler(event: Event) -> None:
        started.set()
        await release.wait()
        finished.append(str(event.type))

    await backend.subscribe(EventTypes.USER_MESSAGE, _handler)
    await backend.start()

    try:
        published = await backend.publish(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"content": "hello"},
            )
        )
        assert published is True
        await asyncio.wait_for(started.wait(), timeout=2.0)

        stop_task = asyncio.create_task(backend.stop())
        await asyncio.sleep(0.1)
        assert stop_task.done() is False

        release.set()
        await asyncio.wait_for(stop_task, timeout=2.0)

        assert finished == [EventTypes.USER_MESSAGE]
    finally:
        release.set()
        if backend._running:
            await backend.stop()


@pytest.mark.asyncio
async def test_publish_snapshots_bound_memory_epoch_and_overwrites_caller_value() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    epoch = 0
    blocker_started = asyncio.Event()
    blocker_release = asyncio.Event()
    received_epochs: list[int | None] = []

    async def _blocker(_event: Event) -> None:
        blocker_started.set()
        await blocker_release.wait()

    async def _handler(event: Event) -> None:
        received_epochs.append(event.metadata.get(PUBLISHED_MEMORY_EPOCH_METADATA_KEY))

    backend.bind_memory_operation_epoch(lambda: epoch)
    await backend.subscribe("BlockerEvent", _blocker)
    await backend.subscribe("EpochEvent", _handler)
    await backend.start()
    try:
        await backend.publish(Event(type="BlockerEvent", data={}))
        await asyncio.wait_for(blocker_started.wait(), timeout=1.0)

        caller_event = Event(
            type="EpochEvent",
            data={},
            metadata={PUBLISHED_MEMORY_EPOCH_METADATA_KEY: 999},
        )
        assert await backend.publish(caller_event) is True

        caller_event.metadata[PUBLISHED_MEMORY_EPOCH_METADATA_KEY] = 1234
        epoch = 1
        blocker_release.set()
        assert backend._queue is not None
        await asyncio.wait_for(backend._queue.join(), timeout=1.0)

        assert received_epochs == [0]
    finally:
        blocker_release.set()
        await backend.stop()


@pytest.mark.asyncio
async def test_create_task_publish_binds_epoch_before_task_is_scheduled() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    epoch = 0
    received_epochs: list[int | None] = []
    backend.bind_memory_operation_epoch(lambda: epoch)

    async def _handler(event: Event) -> None:
        received_epochs.append(event.metadata.get(PUBLISHED_MEMORY_EPOCH_METADATA_KEY))

    await backend.subscribe("DeferredPublishEvent", _handler)
    await backend.start()
    try:
        publish_task = asyncio.create_task(
            backend.publish(Event(type="DeferredPublishEvent", data={}))
        )
        epoch = 1
        assert await publish_task is True
        assert backend._queue is not None
        await asyncio.wait_for(backend._queue.join(), timeout=1.0)

        assert received_epochs == [0]
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_publish_without_memory_epoch_binding_strips_reserved_caller_value() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    received_metadata: list[dict[str, object]] = []

    async def _handler(event: Event) -> None:
        received_metadata.append(dict(event.metadata))

    await backend.subscribe("UnboundEpochEvent", _handler)
    await backend.start()
    try:
        assert await backend.publish(
            Event(
                type="UnboundEpochEvent",
                data={},
                metadata={
                    PUBLISHED_MEMORY_EPOCH_METADATA_KEY: 99,
                    "public": "kept",
                },
            )
        )
        assert backend._queue is not None
        await asyncio.wait_for(backend._queue.join(), timeout=1.0)

        assert received_metadata == [{"public": "kept"}]
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_epoch_getter_failure_does_not_block_non_memory_subscribers() -> None:
    backend = InMemoryMessageBusBackend(num_workers=1)
    received_metadata: list[dict[str, object]] = []

    def _broken_epoch() -> int:
        raise RuntimeError("epoch unavailable")

    async def _handler(event: Event) -> None:
        received_metadata.append(dict(event.metadata))

    backend.bind_memory_operation_epoch(_broken_epoch)
    await backend.subscribe("GetterFailureEvent", _handler)
    await backend.start()
    try:
        assert await backend.publish(
            Event(
                type="GetterFailureEvent",
                data={},
                metadata={
                    PUBLISHED_MEMORY_EPOCH_METADATA_KEY: 99,
                    "public": "kept",
                },
            )
        )
        assert backend._queue is not None
        await asyncio.wait_for(backend._queue.join(), timeout=1.0)

        assert received_metadata == [{"public": "kept"}]
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_backend_instances_keep_independent_memory_epoch_bindings():
    first, fresh = InMemoryMessageBusBackend(num_workers=1), InMemoryMessageBusBackend(
        num_workers=1
    )
    epochs = {"first": 7, "fresh": 0}
    observed = {"first": [], "fresh": []}

    async def receive_first(event):
        observed["first"].append(event.metadata[PUBLISHED_MEMORY_EPOCH_METADATA_KEY])

    async def receive_fresh(event):
        observed["fresh"].append(event.metadata[PUBLISHED_MEMORY_EPOCH_METADATA_KEY])

    first.bind_memory_operation_epoch(lambda: epochs["first"])
    fresh.bind_memory_operation_epoch(lambda: epochs["fresh"])
    await first.subscribe("Epoch", receive_first)
    await fresh.subscribe("Epoch", receive_fresh)
    await first.start()
    await fresh.start()
    try:
        for _ in range(2):
            assert await first.publish(Event(type="Epoch", data={}))
            assert await fresh.publish(Event(type="Epoch", data={}))
            await asyncio.wait_for(
                asyncio.gather(first._queue.join(), fresh._queue.join()), timeout=2
            )
            epochs["first"] = 8
        assert observed == {"first": [7, 8], "fresh": [0, 0]}
    finally:
        await first.stop()
        await fresh.stop()
