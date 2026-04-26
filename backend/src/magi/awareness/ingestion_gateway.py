"""Sensor ingestion gateway — routes SensorOutput to memory, timeline, and other consumers."""

from __future__ import annotations

import inspect
from uuid import uuid4
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

from ..core.logger import get_logger
from ..events.events import EventLevel
from ..memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from ..runtime_defaults import DEFAULT_USER_ID
from ..timeline.contracts import TimelineEvent
from .sensor_base import SensorBase
from .sensor_projection import build_sensor_projection, build_sensor_timeline_event
from .sensor_output import SensorOutput, SensorOutputMetadata
from .sensor_state import SensorStateStore

if TYPE_CHECKING:
    from ..memory import UnifiedMemoryStore
    from ..timeline.adapter import TimelineAdapter
    from ..timeline.insight_pipeline import ALLOWED_EDGE_TYPES

logger = get_logger(__name__)


@dataclass(slots=True)
class SensorIngestionResult:
    """Result of a single sensor output ingestion."""

    event_id: str
    ingested: bool = True
    stats: dict[str, Any] = field(default_factory=dict)


class SensorIngestionGateway:
    """Routes SensorOutput to memory, timeline, and other consumers."""

    def __init__(
        self,
        *,
        unified_memory: UnifiedMemoryStore,
        timeline_adapter: TimelineAdapter | None = None,
        sensor_state_store: SensorStateStore | None = None,
    ) -> None:
        self._unified_memory = unified_memory
        self._timeline_adapter = timeline_adapter
        self._state_store = sensor_state_store

    async def ingest(
        self,
        sensor: SensorBase,
        output: SensorOutput,
        metadata: SensorOutputMetadata | None = None,
        *,
        allowed_edge_whitelist: list[str] | None = None,
    ) -> SensorIngestionResult:
        """Ingest a single SensorOutput through memory, timeline, and knowledge graph."""
        event_id = f"evt_{uuid4().hex}"
        policy = sensor.memory_policy

        # 1. Build MemoryEvent with sensor's policy
        projection = build_sensor_projection(sensor, output)
        timeline_event = build_sensor_timeline_event(
            event_id,
            output,
            projection,
            metadata,
        )
        memory_event = self._build_memory_event(
            sensor,
            event_id,
            output,
            policy,
            metadata=metadata,
            projection_metadata=projection.metadata,
            timeline_event=timeline_event,
        )
        if output.source_type == "calendar":
            logger.info(
                "Calendar memory event prepared",
                event_id=memory_event.event_id,
                source_item_id=memory_event.source_item_id,
                event_type=memory_event.event_type,
                content=memory_event.content,
                metadata_json=memory_event.metadata_json,
            )

        # 2. Ingest into unified memory (L0/L1/L2/L4 as policy dictates)
        memory_result = await self._unified_memory.ingest_event(memory_event)
        stored_event_id = event_id
        if isinstance(memory_result, dict):
            resolved_event_id = memory_result.get("event_id")
            if resolved_event_id is not None and str(resolved_event_id).strip():
                stored_event_id = str(resolved_event_id)

        # 3. Notify timeline adapter (for viewport/query read model)
        if self._timeline_adapter is not None:
            timeline_event.event_id = stored_event_id
            await self._timeline_adapter.on_timeline_event(timeline_event)

        # 4. Process knowledge graph relations
        relation_count = 0
        if metadata and metadata.relation_candidates and allowed_edge_whitelist:
            relation_count = await self._process_relations(
                stored_event_id, output, metadata, sensor, allowed_edge_whitelist,
            )

        # 5. Update sensor state (fingerprint tracking)
        if self._state_store is not None:
            fp = sensor.source_item_version_fingerprint(output.to_dict())
            await self._state_store.add_fingerprints(sensor.sensor_id, {fp})

        return SensorIngestionResult(
            event_id=stored_event_id,
            ingested=True,
            stats={"relation_count": relation_count},
        )

    def _build_memory_event(
        self,
        sensor: SensorBase,
        event_id: str,
        output: SensorOutput,
        policy: Any,
        *,
        metadata: SensorOutputMetadata | None,
        projection_metadata: dict[str, Any],
        timeline_event: TimelineEvent,
    ) -> MemoryEvent:
        """Build a MemoryEvent from SensorOutput + SensorMemoryPolicy."""
        content = timeline_event.summary

        metadata_json = dict(output.domain_payload) if output.domain_payload else {}
        metadata_json.update(projection_metadata)
        l2_batch_policy = sensor.l2_batch_policy(output)
        if l2_batch_policy is not None:
            if l2_batch_policy.owner:
                metadata_json["l2_batch_owner"] = str(l2_batch_policy.owner)
            if l2_batch_policy.catch_up_owner:
                metadata_json["l2_batch_catch_up_owner"] = str(l2_batch_policy.catch_up_owner)
            if l2_batch_policy.max_events is not None:
                metadata_json["l2_batch_max_events"] = int(l2_batch_policy.max_events)
            if l2_batch_policy.min_ready_events is not None:
                metadata_json["l2_batch_min_ready_events"] = int(l2_batch_policy.min_ready_events)
            if l2_batch_policy.max_estimated_tokens is not None:
                metadata_json["l2_batch_max_estimated_tokens"] = int(l2_batch_policy.max_estimated_tokens)
            if l2_batch_policy.max_wait_seconds is not None:
                metadata_json["l2_batch_max_wait_seconds"] = int(l2_batch_policy.max_wait_seconds)
        metadata_json["timeline"] = timeline_event.to_dict()
        if timeline_event.raw_payload_ref:
            metadata_json["raw_payload_ref"] = timeline_event.raw_payload_ref
        if timeline_event.processing_status:
            metadata_json["processing_status"] = dict(timeline_event.processing_status)
        entity_hints = metadata.entities if metadata and metadata.entities else []
        if entity_hints:
            metadata_json["structured_entity_hints"] = entity_hints
        graph_hints = metadata.fact_hints if metadata and metadata.fact_hints else []
        if graph_hints:
            metadata_json["structured_graph_hints"] = graph_hints
        owner_user_id = self._resolve_memory_owner_user_id(output)
        metadata_json["memory_owner_user_id"] = owner_user_id

        return MemoryEvent(
            event_id=event_id,
            correlation_id=event_id,
            timestamp=output.occurred_at,
            created_at=output.captured_at,
            event_type=str(getattr(sensor, "memory_event_type", "SENSOR_EVENT")),
            source=output.source_type,
            source_item_id=output.source_item_id,
            memory_domain=MemoryDomain.from_value(policy.memory_domain),
            ingest_target=IngestTarget.from_value(policy.ingest_target),
            cognition_eligible=policy.cognition_eligible,
            tom_depth=TomDepth.from_value(policy.tom_depth),
            retention_class=RetentionClass.from_value(policy.retention_class),
            session_id=None,
            turn_id=None,
            user_id=owner_user_id,
            task_id=None,
            content=content,
            author_type=policy.author_type,
            content_type=policy.content_type,
            importance_score=policy.importance_bias,
            level=EventLevel.INFO.value,
            idempotency_key=sensor.idempotency_key(output),
            media_path=output.raw_payload_ref,
            metadata_json=metadata_json or None,
        )

    @staticmethod
    def _resolve_memory_owner_user_id(output: SensorOutput) -> str:
        for container in (output.provenance, output.domain_payload):
            if not isinstance(container, dict):
                continue
            for key in ("memory_owner_user_id", "owner_user_id", "user_id"):
                raw_value = str(container.get(key) or "").strip()
                if raw_value:
                    return raw_value
        return DEFAULT_USER_ID

    async def _process_relations(
        self,
        event_id: str,
        output: SensorOutput,
        metadata: SensorOutputMetadata,
        sensor: SensorBase,
        allowed_edge_whitelist: list[str],
    ) -> int:
        """Process knowledge graph relation candidates."""
        from ..timeline.insight_pipeline import ALLOWED_EDGE_TYPES

        allowed = set()
        for edge_type in allowed_edge_whitelist:
            normalized = str(edge_type or "").strip().upper()
            if normalized in ALLOWED_EDGE_TYPES:
                allowed.add(normalized)

        persisted_count = 0
        for candidate in metadata.relation_candidates:
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
            observed_at = float(candidate.get("observed_at", output.occurred_at))
            source_type = str(candidate.get("source_type", output.source_type))

            maybe_awaitable = self._unified_memory.upsert_user_graph_edge(
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
            persisted_count += 1

        return persisted_count
