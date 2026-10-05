from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from magi.memory.event_contracts import IngestTarget
from magi.memory.layer_protocol import FanOutContext
from magi.memory.layers.l1_layer import L1Layer

from ._helpers import make_event


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["USER_MESSAGE", "CUSTOM_SOURCE_EVENT"])
async def test_l1_receives_each_event_kind_through_layer_dispatch(event_type):
    from magi.memory.store_ingestion import MemoryIngestionMixin

    store = AsyncMock()
    store.find_event_id_by_idempotency.return_value = None
    store.store.return_value = "canonical-event"
    layer = L1Layer(store)
    event = make_event(event_type=event_type)
    ctx = FanOutContext()
    await MemoryIngestionMixin()._dispatch_layer(layer, event, ctx)
    store.store.assert_awaited_once_with(event)
    assert ctx.markers == {
        "l1_written": True,
        "l1_confirmed": True,
        "stored_event_id": "canonical-event",
    }
    assert layer.requires_write_lock is True
    assert layer.layer_name == "l1"


def test_l1_accepts_truth_table():
    assert L1Layer(None).accepts(make_event(), FanOutContext()) is False
    layer = L1Layer(AsyncMock())
    assert layer.accepts(make_event(ingest_target=IngestTarget.L1_ONLY), FanOutContext())
    assert not layer.accepts(make_event(ingest_target=IngestTarget.RUNTIME_ONLY), FanOutContext())


@pytest.mark.asyncio
async def test_l1_ingest_writes_when_no_idempotency_hit():
    store = AsyncMock()
    store.find_event_id_by_idempotency.return_value = None
    store.store.return_value = "stored-id"
    layer = L1Layer(store)
    event = make_event()
    result = await layer.ingest(event, FanOutContext())
    store.store.assert_awaited_once_with(event)
    assert result.markers["l1_written"] is True
    assert result.markers["stored_event_id"] == "stored-id"


@pytest.mark.asyncio
async def test_l1_ingest_short_circuits_on_idempotency_hit():
    """When idempotency hit returns the SAME event_id as envelope, use it."""
    store = AsyncMock()
    store.find_event_id_by_idempotency.return_value = "evt_1"  # Match the envelope id
    layer = L1Layer(store)
    result = await layer.ingest(make_event(), FanOutContext())
    store.store.assert_not_awaited()
    assert result.markers["l1_written"] is False
    assert result.markers["stored_event_id"] == "evt_1"


@pytest.mark.asyncio
async def test_l1_ingest_without_finder_writes():
    class StoreNoFinder:
        async def store(self, event):
            return "newid"

    layer = L1Layer(StoreNoFinder())
    result = await layer.ingest(make_event(), FanOutContext())
    assert result.markers == {
        "l1_written": True,
        "l1_confirmed": True,
        "stored_event_id": "newid",
    }
