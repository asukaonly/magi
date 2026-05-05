"""L1 fan-out layer adapter."""
from __future__ import annotations
import logging
from typing import Any

from ..layer_protocol import FanOutContext, LayerIngestResult, MemoryLayer, WILDCARD_EVENT_TYPES
from ..event_contracts import MemoryEvent

logger = logging.getLogger(__name__)


class L1Layer:
    """Adapter wrapping the canonical L1 event store."""

    layer_name = "l1"
    accepts_event_types = WILDCARD_EVENT_TYPES
    requires_write_lock = True

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
            # Dedupe hit. Honor the producer-assigned envelope event_id as the
            # authoritative business id; warn if the legacy row carried a
            # different id (cross-subscriber consistency requires single id).
            if existing_event_id != event.event_id:
                logger.warning(
                    "L1 idempotency hit returned a different event_id; "
                    "honoring envelope id to preserve cross-subscriber consistency "
                    "(envelope_id=%s existing_id=%s idempotency_key=%s source=%s)",
                    event.event_id,
                    existing_event_id,
                    event.idempotency_key,
                    event.source,
                )
            stored_event_id = event.event_id
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
