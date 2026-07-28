"""L4 procedural-memory layer adapter."""

from __future__ import annotations

from typing import Any

from ...events.events import EventTypes
from ..event_contracts import MemoryEvent
from ..layer_protocol import FanOutContext, LayerIngestResult, WILDCARD_EVENT_TYPES


class L4Layer:
    layer_name = "l4"
    requires_write_lock = False
    required_for_acceptance = False
    accepts_event_types = WILDCARD_EVENT_TYPES

    def __init__(self, store: Any) -> None:
        self._store = store

    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool:
        if self._store is None:
            return False
        if event.event_type == EventTypes.ACTION_EXECUTED:
            return True
        return bool(ctx.markers.get("l1_written"))

    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult:
        stored_event_id = ctx.markers.get("stored_event_id")
        if stored_event_id is not None and stored_event_id != event.event_id:
            event.event_id = stored_event_id
        l4_skill_id = await self._store.record_memory_event(event)
        return LayerIngestResult(
            layer_name=self.layer_name,
            ok=True,
            markers={"l4_skill_id": l4_skill_id},
        )


__all__ = ["L4Layer"]
