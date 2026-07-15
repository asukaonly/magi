"""Regression: SensorHub must propagate ``source`` from the published event
into the sensor_event payload — otherwise ``UserMessagePayload.from_dict``
defaults to ``"api"`` and ``_user_message_trigger`` strands every external
inbound (weixin/telegram/…) on a ``source_channel="chat_sse"`` trigger,
which means the reply never fans out back to the originating channel.

This was the actual root cause of the WeChat-silence bug: the dispatch
service correctly set ``UserMessageCommand.source="weixin"``, lifecycle
correctly published it on ``event.data["source"]``, but ``SensorHub.
_on_user_message`` copied a hand-picked subset of fields onto
``sensor_event.payload`` — ``source`` was not in that subset.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from magi.awareness.contracts import SensorEvent
from magi.awareness.sensor_hub import SensorHub
from magi.events.events import Event, EventLevel, EventTypes


def _make_user_message_event(*, source: str) -> Event:
    return Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "content": "hello",
            "attachments": [],
            "user_id": "u-1",
            "session_id": "s-1",
            "turn_id": "t-1",
            "workspace_path": None,
            "metadata": {},
            "timestamp": time.time(),
            "source": source,
        },
        source=source,
        level=EventLevel.INFO,
        correlation_id="cmd_test",
    )


@pytest.mark.asyncio
async def test_on_user_message_propagates_source_to_sensor_event_payload():
    """Phase H+1 plumbing: the ``source`` field must reach the sensor_event
    payload so ``UserMessagePayload.from_dict`` can tag the resulting
    ``RunTrigger.source_channel`` correctly. Without this, external
    inbounds (weixin/telegram) fall through to the chat_sse default and
    the reply never makes it back to the originating channel."""
    bus = AsyncMock()
    hub = SensorHub(message_bus=bus)

    await hub._on_user_message(_make_user_message_event(source="weixin"))

    batch = await hub.get_batch(max_items=1, timeout_seconds=0.5)
    assert len(batch) == 1
    sensor_event = batch[0]
    assert sensor_event.payload.get("source") == "weixin"


@pytest.mark.asyncio
async def test_on_user_message_propagates_telegram_source_too():
    """Same plumbing, different channel — confirms it's not a one-off."""
    bus = AsyncMock()
    hub = SensorHub(message_bus=bus)

    await hub._on_user_message(_make_user_message_event(source="telegram"))

    batch = await hub.get_batch(max_items=1, timeout_seconds=0.5)
    assert len(batch) == 1
    assert batch[0].payload.get("source") == "telegram"


@pytest.mark.asyncio
async def test_on_user_message_defaults_source_to_api_when_event_lacks_one():
    """Legacy events that don't carry ``source`` (pre-Phase-H+1 producers)
    must still produce a valid sensor_event — default to "api" so
    downstream ``_is_external_source`` returns False (native magi)."""
    bus = AsyncMock()
    hub = SensorHub(message_bus=bus)

    # Event with no "source" field in data.
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "content": "hello",
            "user_id": "u-1",
            "session_id": "s-1",
        },
        source="legacy",
        level=EventLevel.INFO,
        correlation_id="cmd_legacy",
    )
    await hub._on_user_message(event)

    batch = await hub.get_batch(max_items=1, timeout_seconds=0.5)
    assert len(batch) == 1
    assert batch[0].payload.get("source") == "api"


@pytest.mark.asyncio
async def test_clear_boundary_discards_stale_queued_user_messages_only():
    bus = AsyncMock()
    hub = SensorHub(message_bus=bus)
    await hub.push_sensor_event(
        SensorEvent(
            sensor_name="user_input_sensor",
            event_type=EventTypes.USER_MESSAGE,
            payload={"session_id": "old-session", "content": "old secret"},
            user_message_generation=0,
        )
    )
    await hub.push_sensor_event(
        SensorEvent(
            sensor_name="calendar",
            event_type="CALENDAR_EVENT",
            payload={"title": "keep event"},
        )
    )
    await hub.push_sensor_event(
        SensorEvent(
            sensor_name="user_input_sensor",
            event_type=EventTypes.USER_MESSAGE,
            payload={"session_id": "new-session", "content": "new message"},
            user_message_generation=1,
        )
    )

    discarded = await hub.discard_stale_user_messages(1)
    batch = await hub.get_batch(max_items=8, timeout_seconds=0.2)

    assert discarded == 1
    assert [(item.event_type, item.payload) for item in batch] == [
        ("CALENDAR_EVENT", {"title": "keep event"}),
        (
            EventTypes.USER_MESSAGE,
            {"session_id": "new-session", "content": "new message"},
        ),
    ]
