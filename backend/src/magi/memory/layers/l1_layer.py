"""L1 event-store layer adapter."""

from __future__ import annotations

from typing import Any

from ..event_contracts import MemoryEvent
from ..layer_protocol import FanOutContext, LayerIngestResult, WILDCARD_EVENT_TYPES


class L1Layer:
    layer_name = "l1"
    requires_write_lock = True
    accepts_event_types = WILDCARD_EVENT_TYPES

    def __init__(self, store: Any) -> None:
        self._store = store

    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool:
        return self._store is not None and event.ingest_target.includes_l1

    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult:
        finder = getattr(self._store, "find_event_id_by_idempotency", None)
        existing_event_id = None
        if callable(finder):
            existing_event_id = await finder(
                source=event.source,
                event_type=event.event_type,
                idempotency_key=event.idempotency_key,
            )
        l1_written = False
        if existing_event_id is not None:
            stored_event_id = existing_event_id
        else:
            stored_event_id = await self._store.store(event)
            l1_written = True
        return LayerIngestResult(
            layer_name=self.layer_name,
            ok=True,
            markers={
                "l1_written": l1_written,
                "stored_event_id": stored_event_id,
            },
        )


__all__ = ["L1Layer"]
