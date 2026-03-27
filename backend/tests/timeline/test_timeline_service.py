from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.timeline.contracts import TimelineEvent
from magi.timeline.service import TimelineService


@pytest.mark.asyncio
async def test_upsert_event_does_not_reingest_into_unified_memory() -> None:
    unified_memory = SimpleNamespace(
        ingest_event=AsyncMock(),
        l1=None,
        l2=None,
        l3=None,
        l4=None,
    )
    service = TimelineService(unified_memory)

    event = TimelineEvent(
        event_id="calendar:item-1",
        source_type="calendar",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        title="Interview",
        summary="Interview",
        retention_mode="analyze_only",
    )

    result = await service.upsert_event(event)

    assert result == "calendar:item-1"
    unified_memory.ingest_event.assert_not_awaited()
