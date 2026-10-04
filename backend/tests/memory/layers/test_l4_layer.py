from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from magi.events.events import EventTypes
from magi.memory.layer_protocol import FanOutContext
from magi.memory.layers.l4_layer import L4Layer
from magi.memory.store_ingestion import MemoryIngestionMixin

from ._helpers import make_event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_store,event_type,l1_written,accepted",
    [
        (False, EventTypes.ACTION_EXECUTED, False, False),
        (False, EventTypes.ACTION_EXECUTED, True, False),
        (False, "PLUGIN_OBSERVATION", False, False),
        (False, "PLUGIN_OBSERVATION", True, False),
        (True, EventTypes.ACTION_EXECUTED, False, True),
        (True, EventTypes.ACTION_EXECUTED, True, True),
        (True, "PLUGIN_OBSERVATION", False, False),
        (True, "PLUGIN_OBSERVATION", True, True),
    ],
)
async def test_dispatch_records_only_admitted_events(has_store, event_type, l1_written, accepted):
    store = AsyncMock()
    store.record_memory_event.return_value = "skill-accepted"
    event = make_event(event_type=event_type)
    ctx = FanOutContext(markers={"l1_written": l1_written})
    await MemoryIngestionMixin()._dispatch_layer(L4Layer(store if has_store else None), event, ctx)
    if accepted:
        store.record_memory_event.assert_awaited_once_with(event)
        assert ctx.markers == {"l1_written": l1_written, "l4_skill_id": "skill-accepted"}
    else:
        store.record_memory_event.assert_not_awaited()
        assert ctx.markers == {"l1_written": l1_written}


@pytest.mark.asyncio
async def test_ingestion_defers_l4_until_after_the_shared_write_lock():
    import asyncio
    from types import SimpleNamespace

    ingestion = MemoryIngestionMixin()
    ingestion.l1 = ingestion.l2 = None
    ingestion._write_lock = asyncio.Lock()
    ingestion._govern_event_time_range = AsyncMock(
        return_value=SimpleNamespace(delete_l1_event=False, blocks_derivations=False)
    )
    ingestion._any_source_reference_is_tombstoned = AsyncMock(return_value=False)

    async def record(event):
        assert not ingestion._write_lock.locked()
        return "deferred-skill"

    ingestion.l4 = AsyncMock()
    ingestion.l4.record_memory_event.side_effect = record
    event = make_event(event_type=EventTypes.ACTION_EXECUTED)
    result = await ingestion._ingest_memory_event(event)
    ingestion.l4.record_memory_event.assert_awaited_once_with(event)
    assert result["l4_skill_id"] == "deferred-skill"


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
    assert result.layer_name == "l4"
