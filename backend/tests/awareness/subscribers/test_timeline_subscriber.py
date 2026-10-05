"""Phase 5 of C: TimelineSubscriber projects SourceEventEmitted to timeline read model."""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SourceEventEmitted, TaskContext
from magi.timeline.subscribers.timeline_subscriber import TimelineSubscriber


def _make_payload(**overrides):
    base = dict(
        source_name="screen_time",
        payload={
            "source_type": "external_activity",
            "source_item_id": "x",
            "occurred_at": 1.0,
            "captured_at": 1.5,
            "domain_payload": {},
            "raw_payload_ref": None,
            "provenance": {},
            "tags": [],
            "entities": [],
            "content_blocks": [],
        },
        context=TaskContext(None, None, None, "u"),
        source_id="screen_time",
        output_dict={
            "source_type": "external_activity",
            "source_item_id": "x",
            "occurred_at": 1.0,
            "captured_at": 1.5,
            "domain_payload": {},
            "raw_payload_ref": None,
            "provenance": {},
            "tags": [],
            "entities": [],
            "content_blocks": [],
        },
        metadata_dict={},
        policy_dict={"memory_domain": "external_activity"},
        projection_dict={"title": "T", "summary": "S", "content": "C", "embedding_head": "H", "metadata": {}},
        occurred_at=1.0,
        owner_user_id="u",
    )
    base.update(overrides)
    return SourceEventEmitted(**base)


@pytest.fixture
def fake_adapter():
    a = MagicMock()
    a.on_timeline_event = AsyncMock()
    return a


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_first", [False, True])
async def test_registered_timeline_subscriber_delivers_recovers_and_unsubscribes(
    fake_adapter, fail_first, caplog
):
    from magi.events.in_memory_backend import InMemoryMessageBusBackend

    bus = InMemoryMessageBusBackend()
    await bus.start()
    if fail_first:
        fake_adapter.on_timeline_event.side_effect = [RuntimeError("adapter failed"), None]
    sub = TimelineSubscriber(event_bus=bus, timeline_adapter=fake_adapter)
    try:
        await sub.start()
        for event_id in ["first", "second"]:
            await bus.publish(
                Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=_make_payload(), event_id=event_id)
            )
            await asyncio.wait_for(bus._queue.join(),timeout=1)
            await sub.drain()
        delivered = [call.args[0] for call in fake_adapter.on_timeline_event.await_args_list]
        assert [event.event_id for event in delivered] == ["first", "second"]
        assert [event.source_item_id for event in delivered] == ["x", "x"]
        if fail_first:
            assert "adapter failed" in caplog.text
        await sub.stop()
        await bus.publish(
            Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=_make_payload(), event_id="after-stop")
        )
        await asyncio.wait_for(bus._queue.join(),timeout=1)
        await sub.drain()
        assert fake_adapter.on_timeline_event.await_count == 2
    finally:
        await sub.stop()
        await bus.stop()
