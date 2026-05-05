"""Project SensorEventEmitted relation candidates into the knowledge graph."""
from __future__ import annotations
import asyncio
import inspect
import logging
from typing import Any, Mapping, Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SensorEventEmitted
from magi.events.payload_helpers import expect_payload, PayloadTypeError

logger = logging.getLogger(__name__)


class KGSubscriber:
    def __init__(self, *, event_bus, unified_memory) -> None:
        self._bus = event_bus
        self._memory = unified_memory
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SENSOR_EVENT_EMITTED, self._on_event,
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("kg_subscriber unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SensorEventEmitted)
        except PayloadTypeError:
            return
        if not payload.relation_candidates or not payload.allowed_edge_whitelist:
            return
        task = asyncio.create_task(self._safe_process_relations(
            event_id=event.event_id,
            output_dict=payload.output_dict,
            relation_candidates=payload.relation_candidates,
            allowed_edge_whitelist=payload.allowed_edge_whitelist,
        ))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_process_relations(
        self,
        *,
        event_id: str,
        output_dict: Mapping[str, Any],
        relation_candidates: tuple[Mapping[str, Any], ...],
        allowed_edge_whitelist: tuple[str, ...],
    ) -> None:
        from magi.timeline.insight_pipeline import ALLOWED_EDGE_TYPES

        allowed = set()
        for edge_type in allowed_edge_whitelist:
            normalized = str(edge_type or "").strip().upper()
            if normalized in ALLOWED_EDGE_TYPES:
                allowed.add(normalized)

        default_occurred_at = float(output_dict.get("occurred_at") or 0.0)
        default_source_type = str(output_dict.get("source_type") or "")

        for candidate in relation_candidates:
            try:
                predicate = str(candidate.get("predicate", "")).strip().upper()
                if predicate not in ALLOWED_EDGE_TYPES or predicate not in allowed:
                    continue
                object_id = str(candidate.get("object_id", "")).strip()
                if not object_id:
                    continue

                subject_id = str(candidate.get("subject_id", "user:self"))
                subject_type = str(candidate.get("subject_type", "user"))
                object_type = str(candidate.get("object_type", "topic"))
                confidence = float(candidate.get("confidence", 0.5))
                observed_at = float(candidate.get("observed_at", default_occurred_at))
                source_type = str(candidate.get("source_type", default_source_type))

                maybe_awaitable = self._memory.upsert_user_graph_edge(
                    subject_id=subject_id,
                    subject_type=subject_type,
                    predicate=predicate,
                    object_id=object_id,
                    object_type=object_type,
                    fact_kind=str(candidate.get("fact_kind", "")).strip() or None,
                    evidence_event_ids=[event_id],
                    confidence=confidence,
                    observed_at=observed_at,
                    source_type=source_type,
                    subject_attributes=dict(candidate.get("subject_attributes", {})),
                    object_attributes=dict(candidate.get("object_attributes", {})),
                )
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
            except Exception:
                logger.exception(
                    "kg upsert_user_graph_edge failed (event_id=%s candidate=%s)",
                    event_id, candidate,
                )
