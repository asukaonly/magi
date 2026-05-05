"""L0 working-memory layer adapter."""

from __future__ import annotations

from typing import Any

from ..event_contracts import MemoryEvent
from ..layer_protocol import FanOutContext, LayerIngestResult, WILDCARD_EVENT_TYPES


class L0Layer:
    layer_name = "l0"
    requires_write_lock = True
    accepts_event_types = WILDCARD_EVENT_TYPES

    def __init__(self, store: Any) -> None:
        self._store = store

    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool:
        return self._store is not None

    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult:
        await self._store.capture_event(event)
        return LayerIngestResult(layer_name=self.layer_name, ok=True)


__all__ = ["L0Layer"]
