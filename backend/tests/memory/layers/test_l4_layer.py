from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from magi.events.events import EventTypes
from magi.memory.layer_protocol import FanOutContext, WILDCARD_EVENT_TYPES
from magi.memory.layers.l4_layer import L4Layer

from ._helpers import make_event


def test_l4_basics():
    layer = L4Layer(AsyncMock())
    assert layer.accepts_event_types == WILDCARD_EVENT_TYPES
    assert layer.requires_write_lock is False
    assert layer.layer_name == "l4"


def test_l4_rejects_without_store():
    assert not L4Layer(None).accepts(make_event(), FanOutContext())


def test_l4_accepts_action_executed():
    layer = L4Layer(AsyncMock())
    event = make_event(event_type=EventTypes.ACTION_EXECUTED)
    assert layer.accepts(event, FanOutContext())


def test_l4_accepts_when_l1_written():
    layer = L4Layer(AsyncMock())
    ctx = FanOutContext(markers={"l1_written": True})
    assert layer.accepts(make_event(), ctx)


def test_l4_rejects_when_neither_action_nor_l1_written():
    layer = L4Layer(AsyncMock())
    assert not layer.accepts(make_event(), FanOutContext())


@pytest.mark.asyncio
async def test_l4_ingest_records_and_rewrites_event_id():
    store = AsyncMock()
    store.record_memory_event.return_value = "skill-123"
    layer = L4Layer(store)
    event = make_event(event_id="orig")
    ctx = FanOutContext(markers={"stored_event_id": "rewritten", "l1_written": True})
    result = await layer.ingest(event, ctx)
    assert event.event_id == "rewritten"
    store.record_memory_event.assert_awaited_once_with(event)
    assert result.markers == {"l4_skill_id": "skill-123"}
