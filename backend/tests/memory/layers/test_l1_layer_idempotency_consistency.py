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
