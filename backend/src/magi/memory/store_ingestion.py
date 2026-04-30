"""Event ingestion path for the unified memory store."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ..events.events import Event, EventLevel, EventTypes
from .event_contracts import MemoryEvent, normalize_runtime_event
from .l2.models import ManualL2EventRequest

logger = logging.getLogger(__name__)

MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES = {
    EventTypes.USER_MESSAGE,
    EventTypes.AI_RESPONSE,
    EventTypes.ACTION_EXECUTED,
}


class MemoryIngestionMixin:
    """Coordinates L0-L4 writes for normalized memory events."""

    l0: Any
    l1: Any
    l2: Any
    l2_pipeline: Any
    l4: Any
    _write_lock: Any

    async def ingest_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> Dict[str, Any]:
        """Ingest an event through the new L0-L4 pipeline."""
        memory_event = self._normalize_event(event)
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
        l2_result = {"relation_count": 0, "assertion_count": 0}
        l4_skill_id: Optional[str] = None
        l1_written = False
        stored_event_id = memory_event.event_id
        l2_job_enqueued = False

        async with self._write_lock:
            if self.l0 is not None:
                await self.l0.capture_event(memory_event)

            if self.l1 is not None and memory_event.ingest_target.includes_l1:
                finder = getattr(self.l1, "find_event_id_by_idempotency", None)
                existing_event_id = None
                if callable(finder):
                    existing_event_id = await finder(
                        source=memory_event.source,
                        event_type=memory_event.event_type,
                        idempotency_key=memory_event.idempotency_key,
                    )
                if existing_event_id is not None:
                    stored_event_id = existing_event_id
                else:
                    stored_event_id = await self.l1.store(memory_event)
                    l1_written = True
                if memory_event.event_type in MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES:
                    logger.info(
                        "UnifiedMemory stored event in L1 | event_id=%s type=%s session_id=%s user_id=%s",
                        stored_event_id,
                        memory_event.event_type,
                        memory_event.session_id,
                        memory_event.user_id,
                    )
                if self.l2 is not None and memory_event.cognition_eligible:
                    l2_job_enqueued = await self.l2.enqueue_projection_job(
                        event_id=stored_event_id,
                        source=memory_event.source,
                        event_type=memory_event.event_type,
                        batch_owner=(
                            str(memory_event.metadata_json.get("l2_batch_owner"))
                            if isinstance(memory_event.metadata_json, dict)
                            and memory_event.metadata_json.get("l2_batch_owner") is not None
                            else None
                        ),
                        catch_up_owner=(
                            str(memory_event.metadata_json.get("l2_batch_catch_up_owner"))
                            if isinstance(memory_event.metadata_json, dict)
                            and memory_event.metadata_json.get("l2_batch_catch_up_owner") is not None
                            else None
                        ),
                        max_events=(
                            int(memory_event.metadata_json.get("l2_batch_max_events"))
                            if isinstance(memory_event.metadata_json, dict)
                            and memory_event.metadata_json.get("l2_batch_max_events") is not None
                            else None
                        ),
                        min_ready_events=(
                            int(memory_event.metadata_json.get("l2_batch_min_ready_events"))
                            if isinstance(memory_event.metadata_json, dict)
                            and memory_event.metadata_json.get("l2_batch_min_ready_events") is not None
                            else None
                        ),
                        max_wait_seconds=(
                            float(memory_event.metadata_json.get("l2_batch_max_wait_seconds"))
                            if isinstance(memory_event.metadata_json, dict)
                            and memory_event.metadata_json.get("l2_batch_max_wait_seconds") is not None
                            else None
                        ),
                    )

        if (
            self.l2_pipeline is not None
            and memory_event.cognition_eligible
            and (not memory_event.ingest_target.includes_l1 or self.l2 is None)
        ):
            if stored_event_id != memory_event.event_id:
                memory_event.event_id = stored_event_id
            await self.l2_pipeline.enqueue_event(memory_event)
        if self.l4 is not None and (l1_written or memory_event.event_type == EventTypes.ACTION_EXECUTED):
            if stored_event_id != memory_event.event_id:
                memory_event.event_id = stored_event_id
            l4_skill_id = await self.l4.record_memory_event(memory_event)

        return {
            "event_id": stored_event_id,
            "ingest_target": memory_event.ingest_target.label,
            "l1_written": l1_written,
            "l2_job_enqueued": l2_job_enqueued,
            "l2_relation_count": int(l2_result["relation_count"]),
            "l2_assertion_count": int(l2_result["assertion_count"]),
            "l4_skill_id": l4_skill_id,
        }

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
                logger.info(
                    "Calendar memory normalization used canonical MemoryEvent path | "
                    "event_id=%s event_type=%s source_item_id=%s content=%s",
                    event.event_id,
                    event.event_type,
                    event.source_item_id,
                    event.content,
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
        raw_event = Event(
            type=str(payload.get("type", "unknown")),
            data=payload.get("data", {}),
            timestamp=float(payload.get("timestamp", time.time())),
            source=str(payload.get("source", "memory")),
            level=EventLevel(int(payload.get("level", EventLevel.INFO.value))),
            correlation_id=payload.get("correlation_id"),
            metadata=dict(payload.get("metadata", {})),
        )
        legacy_event_id = payload.get("id")
        if not isinstance(legacy_event_id, str):
            legacy_event_id = None
        return normalize_runtime_event(
            raw_event,
            event_id=payload.get("event_id") or legacy_event_id,
            idempotency_key=payload.get("idempotency_key"),
        )


__all__ = ["MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES", "MemoryIngestionMixin"]