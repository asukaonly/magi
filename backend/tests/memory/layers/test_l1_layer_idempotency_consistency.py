"""L1 idempotency must keep downstream layers on canonical L1 event ids."""
from __future__ import annotations
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.memory.layer_protocol import FanOutContext
from magi.memory.layers.l1_layer import L1Layer


def _make_event(*, event_id: str, idempotency_key: str = "k1"):
    """Minimal MemoryEvent-like duck for L1Layer."""
    ev = MagicMock()
    ev.event_id = event_id
    ev.idempotency_key = idempotency_key
    ev.source = "source"
    ev.event_type = "SOURCE_EVENT"
    # ingest_target.includes_l1 = True
    ev.ingest_target.includes_l1 = True
    return ev


@pytest.mark.asyncio
async def test_idempotency_match_uses_existing_id():
    """When find returns the SAME id as envelope, use it without warning."""
    store = MagicMock()
    store.find_event_id_by_idempotency = AsyncMock(return_value="evt-same")
    store.store = AsyncMock()
    layer = L1Layer(store)
    event = _make_event(event_id="evt-same")
    result = await layer.ingest(event, FanOutContext())
    assert result.markers["stored_event_id"] == "evt-same"
    assert result.markers["l1_written"] is False
    store.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotency_miss_writes_and_uses_envelope_id():
    """No dedupe hit: store + use envelope id."""
    store = MagicMock()
    store.find_event_id_by_idempotency = AsyncMock(return_value=None)
    store.store = AsyncMock(return_value="evt-fresh")
    layer = L1Layer(store)
    event = _make_event(event_id="evt-fresh")
    result = await layer.ingest(event, FanOutContext())
    assert result.markers["l1_written"] is True
    # stored_event_id is whatever the store returned (consistent with current behavior)
    assert result.markers["stored_event_id"] == "evt-fresh"
    store.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotency_mismatch_warns_and_uses_existing_id(caplog):
    """When find returns a DIFFERENT id, log warning, dedupe, use existing L1 id."""
    store = MagicMock()
    store.find_event_id_by_idempotency = AsyncMock(return_value="evt-OLD")
    store.store = AsyncMock()
    layer = L1Layer(store)
    event = _make_event(event_id="evt-NEW", idempotency_key="key-1")
    with caplog.at_level(logging.WARNING):
        result = await layer.ingest(event, FanOutContext())
    # Did not double-INSERT
    store.store.assert_not_awaited()
    # markers: NOT written (dedupe hit), and downstream layers get the canonical L1 id.
    assert result.markers["l1_written"] is False
    assert result.markers["stored_event_id"] == "evt-OLD"
    # Warning logged
    assert any(
        "idempotency" in record.message.lower() and "evt-OLD" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_no_idempotency_finder_writes_normally():
    """Backward compat: stores without find_event_id_by_idempotency just store."""
    store = MagicMock(spec=["store"])  # no find_event_id_by_idempotency
    store.store = AsyncMock(return_value="evt-fresh")
    layer = L1Layer(store)
    event = _make_event(event_id="evt-fresh")
    result = await layer.ingest(event, FanOutContext())
    assert result.markers["l1_written"] is True
    assert result.markers["stored_event_id"] == "evt-fresh"
