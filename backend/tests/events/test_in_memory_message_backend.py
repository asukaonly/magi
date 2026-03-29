from __future__ import annotations

import asyncio

import pytest

from magi.events.events import (
    Event,
    EventTypes,
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
