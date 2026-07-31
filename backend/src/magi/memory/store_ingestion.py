"""Event ingestion path for the unified memory store."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from ..core.sqlite import sqlite_connection_async
from ..events.events import Event, EventLevel, EventTypes
from ..utils.diagnostic_logging import full_content_logging_enabled
from .event_contracts import MemoryEvent, normalize_runtime_event
from .l2.models import ManualL2EventRequest
from .layer_protocol import FanOutContext, MemoryLayer, WILDCARD_EVENT_TYPES
from .layers import L1Layer, L2PipelineLayer, L2ProjectionLayer, L4Layer
from .source_event_governance import (
    TimeRangeGovernanceDecision,
    govern_source_events_by_time_range,
    memory_event_source_references,
)

logger = logging.getLogger(__name__)

MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES = {
    EventTypes.USER_MESSAGE,
    EventTypes.AI_RESPONSE,
    EventTypes.ACTION_EXECUTED,
}


class MemoryIngestionMixin:
    """Coordinates durable-memory writes for normalized memory events."""

    l0: Any
    l1: Any
    l2: Any
    l2_pipeline: Any
    l4: Any
    _write_lock: Any
    _clear_barrier: Any
    _clear_epoch: int

    async def ingest_event(
        self,
        event: Dict[str, Any] | Event | MemoryEvent,
        *,
        expected_epoch: int | None = None,
    ) -> Dict[str, Any]:
        """Ingest an event through the durable-memory pipeline."""
        memory_event = self._normalize_event(event)
        captured_epoch = int(self._clear_epoch) if expected_epoch is None else int(expected_epoch)
        async with self._clear_barrier.operation():
            if captured_epoch != int(self._clear_epoch):
                return {
                    "event_id": memory_event.event_id,
                    "ingest_target": memory_event.ingest_target.label,
                    "l1_written": False,
                    "l1_confirmed": False,
                    "l2_job_enqueued": False,
                    "l2_relation_count": 0,
                    "l2_assertion_count": 0,
                    "l4_skill_id": None,
                    "skipped": True,
                    "skip_reason": "memory_clear_epoch_changed",
                }
            return await self._ingest_memory_event(memory_event)

    async def _ingest_memory_event(self, memory_event: MemoryEvent) -> Dict[str, Any]:
        """Fan one normalized event out while destructive clears are excluded."""
        if memory_event.event_type in MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "UnifiedMemory normalized event | event_id=%s type=%s ingest_target=%s memory_domain=%s session_id=%s user_id=%s correlation_id=%s",
                memory_event.event_id,
                memory_event.event_type,
                memory_event.ingest_target.label,
                memory_event.memory_domain.label,
                memory_event.session_id,
                memory_event.user_id,
                memory_event.correlation_id,
            )

        ctx = FanOutContext()
        layers = self._build_layers_in_order()
        locked_layers = [layer for layer in layers if layer.requires_write_lock]
        deferred_layers = [layer for layer in layers if not layer.requires_write_lock]

        async with self._write_lock:
            time_range_decision = await self._govern_event_time_range(memory_event)
            if time_range_decision.delete_l1_event:
                return self._forgotten_time_range_result(memory_event)
            if await self._any_source_reference_is_tombstoned(
                memory_event_source_references(memory_event),
                turn_id=memory_event.turn_id,
                accepted_at=memory_event.created_at,
            ):
                return self._forgotten_source_result(memory_event)
            for layer in locked_layers:
                if time_range_decision.blocks_derivations and layer.layer_name != "l1":
                    continue
                await self._dispatch_layer(layer, memory_event, ctx)
                if (
                    layer.layer_name == "l1"
                    and ctx.markers.get("stored_event_id") is not None
                    and memory_event.event_type in MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES
                ):
                    logger.info(
                        "UnifiedMemory stored event in L1 | event_id=%s type=%s session_id=%s user_id=%s",
                        ctx.markers.get("stored_event_id"),
                        memory_event.event_type,
                        memory_event.session_id,
                        memory_event.user_id,
                    )

        if time_range_decision.blocks_derivations:
            stored_event_id = ctx.markers.get("stored_event_id") or memory_event.event_id
            return {
                "event_id": stored_event_id,
                "ingest_target": memory_event.ingest_target.label,
                "l1_written": bool(ctx.markers.get("l1_written")),
                "l1_confirmed": bool(ctx.markers.get("l1_confirmed")),
                "l2_job_enqueued": False,
                "l2_relation_count": 0,
                "l2_assertion_count": 0,
                "l4_skill_id": None,
                "skipped_derivations": True,
                "skip_reason": "time_range_forgotten",
            }

        for layer in deferred_layers:
            await self._dispatch_layer(layer, memory_event, ctx)

        stored_event_id = ctx.markers.get("stored_event_id") or memory_event.event_id
        return {
            "event_id": stored_event_id,
            "ingest_target": memory_event.ingest_target.label,
            "l1_written": bool(ctx.markers.get("l1_written")),
            "l1_confirmed": bool(ctx.markers.get("l1_confirmed")),
            "l2_job_enqueued": bool(ctx.markers.get("l2_job_enqueued")),
            "l2_relation_count": 0,
            "l2_assertion_count": 0,
            "l4_skill_id": ctx.markers.get("l4_skill_id"),
        }

    @staticmethod
    def _forgotten_source_result(memory_event: MemoryEvent) -> Dict[str, Any]:
        """Return the fail-closed result for an event behind a delete barrier."""
        return {
            "event_id": memory_event.event_id,
            "ingest_target": memory_event.ingest_target.label,
            "l1_written": False,
            "l1_confirmed": False,
            "l2_job_enqueued": False,
            "l2_relation_count": 0,
            "l2_assertion_count": 0,
            "l4_skill_id": None,
            "skipped": True,
            "skip_reason": "source_event_forgotten",
        }

    @staticmethod
    def _forgotten_time_range_result(memory_event: MemoryEvent) -> Dict[str, Any]:
        """Return the result for a source occurrence removed by a durable range."""
        return {
            "event_id": memory_event.event_id,
            "ingest_target": memory_event.ingest_target.label,
            "l1_written": False,
            "l1_confirmed": False,
            "l2_job_enqueued": False,
            "l2_relation_count": 0,
            "l2_assertion_count": 0,
            "l4_skill_id": None,
            "skipped": True,
            "skip_reason": "time_range_forgotten",
        }

    async def _govern_event_time_range(
        self,
        memory_event: MemoryEvent,
    ) -> TimeRangeGovernanceDecision:
        """Publish event-specific blocks before a matching event can enter L1."""
        async with sqlite_connection_async(self.memory_db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                decision = await govern_source_events_by_time_range(
                    db,
                    event_ids=(memory_event.event_id, memory_event.turn_id),
                    observed_from=float(memory_event.timestamp),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return decision

    async def _dispatch_layer(
        self,
        layer: MemoryLayer,
        event: MemoryEvent,
        ctx: FanOutContext,
    ) -> None:
        accepted_types = layer.accepts_event_types
        if accepted_types != WILDCARD_EVENT_TYPES and event.event_type not in accepted_types:
            return
        if not layer.accepts(event, ctx):
            return
        try:
            result = await layer.ingest(event, ctx)
        except Exception:
            logger.exception(
                "UnifiedMemory layer ingest failed | layer=%s event_id=%s event_type=%s",
                layer.layer_name,
                event.event_id,
                event.event_type,
            )
            if layer.required_for_acceptance:
                raise
            return
        if result.markers:
            ctx.markers.update(result.markers)

    def _build_layers_in_order(self) -> list[MemoryLayer]:
        return [
            L1Layer(self.l1),
            L2ProjectionLayer(
                self.l2,
                batch_flush_interval_seconds=getattr(
                    self, "_l2_batch_flush_interval_seconds", None
                ),
            ),
            L2PipelineLayer(self.l2, self.l2_pipeline),
            L4Layer(self.l4),
        ]

    async def store_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> str:
        """Compatibility helper for callers that only need the event id."""
        result = await self.ingest_event(event)
        return str(result["event_id"])

    async def add_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> str:
        """Store an event in the unified pipeline."""
        return await self.store_event(event)

    async def ingest_manual_l2_event(self, request: ManualL2EventRequest) -> Dict[str, Any]:
        """Inject a manual event into the normal L1 -> L2 path for testing."""
        payload = {
            "user_id": request.user_id,
            "session_id": request.session_id or f"manual-{request.user_id}",
            "content": request.text,
            "author_type": "user",
            "content_type": "text",
        }
        metadata = {
            "manual_l2_lab": True,
        }
        return await self.ingest_event(
            Event(
                type="USER_MESSAGE",
                data=payload,
                timestamp=time.time(),
                source=request.source,
                level=EventLevel.INFO,
                metadata=metadata,
                correlation_id=f"manual_{int(time.time() * 1000)}",
            )
        )

    def _normalize_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> MemoryEvent:
        if isinstance(event, MemoryEvent):
            if str(getattr(event, "source", "")) == "calendar":
                if full_content_logging_enabled():
                    logger.info(
                        "Calendar memory normalization used canonical "
                        "MemoryEvent path | event_id=%s event_type=%s "
                        "source_item_id=%s content=%s",
                        event.event_id,
                        event.event_type,
                        event.source_item_id,
                        event.content,
                    )
                else:
                    logger.info(
                        "Calendar memory normalization used canonical "
                        "MemoryEvent path | event_id=%s event_type=%s "
                        "content_chars=%d",
                        event.event_id,
                        event.event_type,
                        len(event.content),
                    )
            return event
        if isinstance(event, Event):
            if str(getattr(event, "source", "")) == "calendar":
                logger.warning(
                    "Calendar memory normalization fell back to runtime Event path | "
                    "event_type=%s correlation_id=%s",
                    event.type,
                    event.correlation_id,
                )
            return normalize_runtime_event(event)

        payload = dict(event)
        if str(payload.get("source", "")) == "calendar":
            logger.warning(
                "Calendar memory normalization fell back to dict path | "
                "payload_keys=%s payload_event_id=%s payload_type=%s payload_source=%s",
                sorted(payload.keys()),
                payload.get("event_id"),
                payload.get("type"),
                payload.get("source"),
            )
        legacy_event_id = payload.get("id")
        if not isinstance(legacy_event_id, str):
            legacy_event_id = None
        envelope_event_id = payload.get("event_id") or legacy_event_id
        raw_event = Event(
            type=str(payload.get("type", "unknown")),
            data=payload.get("data", {}),
            timestamp=float(payload.get("timestamp", time.time())),
            source=str(payload.get("source", "memory")),
            level=EventLevel(int(payload.get("level", EventLevel.INFO.value))),
            correlation_id=payload.get("correlation_id"),
            event_id=envelope_event_id,
            metadata=dict(payload.get("metadata", {})),
        )
        return normalize_runtime_event(
            raw_event,
            idempotency_key=payload.get("idempotency_key"),
        )


__all__ = ["MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES", "MemoryIngestionMixin"]
