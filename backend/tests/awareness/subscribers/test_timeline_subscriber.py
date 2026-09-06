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
def fake_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    bus.unsubscribe = AsyncMock(return_value=True)
    return bus


@pytest.fixture
def fake_adapter():
    a = MagicMock()
    a.on_timeline_event = AsyncMock()
    return a


@pytest.mark.asyncio
async def test_subscribes_to_source_event_emitted(fake_bus, fake_adapter):
    sub = TimelineSubscriber(event_bus=fake_bus, timeline_adapter=fake_adapter)
    await sub.start()
    fake_bus.subscribe.assert_awaited_once()
    assert fake_bus.subscribe.await_args.args[0] == EventTypes.SOURCE_EVENT_EMITTED


@pytest.mark.asyncio
async def test_dispatches_timeline_event_with_envelope_id(fake_bus, fake_adapter):
    sub = TimelineSubscriber(event_bus=fake_bus, timeline_adapter=fake_adapter)
    await sub.start()
    payload = _make_payload()
    await sub._on_event(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="evt-XX"))
    await sub.drain()
    fake_adapter.on_timeline_event.assert_awaited_once()
    timeline_event = fake_adapter.on_timeline_event.await_args.args[0]
    assert timeline_event.event_id == "evt-XX"


@pytest.mark.asyncio
async def test_handler_failure_does_not_break_subscriber(fake_bus, fake_adapter):
    fake_adapter.on_timeline_event.side_effect = RuntimeError("dead")
    sub = TimelineSubscriber(event_bus=fake_bus, timeline_adapter=fake_adapter)
    await sub.start()
    payload = _make_payload()
    await sub._on_event(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="evt-1"))
    await sub.drain()  # must not raise


@pytest.mark.asyncio
async def test_stop_unsubscribes(fake_bus, fake_adapter):
    sub = TimelineSubscriber(event_bus=fake_bus, timeline_adapter=fake_adapter)
    await sub.start()
    await sub.stop()
    fake_bus.unsubscribe.assert_awaited_once()
