"""Retired direct knowledge-graph subscriber.

Relation candidates are now routed through L2 ``structured_graph_hints`` so all
graph writes pass through L2 evidence classification, ExtractionProfile
allowlists, promotion gating, and durable forgetting barriers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from magi.events.domain_payloads import SourceEventEmitted
from magi.events.events import Event, EventTypes
from magi.events.payload_helpers import PayloadTypeError, expect_payload

logger = logging.getLogger(__name__)


class KGSubscriber:
    """No-op guard that blocks direct SourceEventEmitted -> KG bypass writes."""

    def __init__(self, *, event_bus, kg_writer) -> None:
        self._bus = event_bus
        self._writer = kg_writer
        self._sub_id: Optional[str] = None
        self._bypass_blocked_count = 0

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SOURCE_EVENT_EMITTED,
            self._on_event,
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("kg_subscriber unsubscribe failed")
            self._sub_id = None

    async def drain(self) -> None:
        return None

    def get_stats(self) -> Any:
        base = self._writer.get_stats() if hasattr(self._writer, "get_stats") else {}
        if isinstance(base, dict):
            return {**base, "bypass_blocked": self._bypass_blocked_count}
        return {"bypass_blocked": self._bypass_blocked_count}

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SourceEventEmitted)
        except PayloadTypeError:
            return
        if payload.relation_candidates:
            self._bypass_blocked_count += len(payload.relation_candidates)
            logger.debug(
                "Skipped direct KG bypass for event_id=%s count=%d; governed via L2 structured_graph_hints",
                event.event_id,
                len(payload.relation_candidates),
            )
