from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from magi.memory.layer_protocol import FanOutContext, WILDCARD_EVENT_TYPES
from magi.memory.layers.l0_layer import L0Layer

from ._helpers import make_event


def test_l0_accepts_event_types_is_wildcard():
    layer = L0Layer(AsyncMock())
    assert layer.accepts_event_types == WILDCARD_EVENT_TYPES
    assert layer.requires_write_lock is True
    assert layer.layer_name == "l0"


def test_l0_accepts_when_store_present():
    assert L0Layer(AsyncMock()).accepts(make_event(), FanOutContext()) is True


def test_l0_rejects_when_store_missing():
    assert L0Layer(None).accepts(make_event(), FanOutContext()) is False


@pytest.mark.asyncio
async def test_l0_ingest_calls_capture_event():
    store = AsyncMock()
    layer = L0Layer(store)
    event = make_event()
    result = await layer.ingest(event, FanOutContext())
    store.capture_event.assert_awaited_once_with(event)
    assert result.layer_name == "l0"
    assert result.ok is True


@pytest.mark.asyncio
async def test_l0_ingest_propagates_exceptions():
    store = AsyncMock()
    store.capture_event.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        await L0Layer(store).ingest(make_event(), FanOutContext())
