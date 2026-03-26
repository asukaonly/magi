"""Sensor ingestion gateway — routes SensorOutput to memory, timeline, and other consumers."""

from __future__ import annotations

import inspect
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
from .sensor_base import SensorBase
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
        event_id = f"{output.source_type}:{output.source_item_id}"
        policy = sensor.memory_policy

        # 1. Build MemoryEvent with sensor's policy
        memory_event = self._build_memory_event(event_id, output, policy)

        # 2. Ingest into unified memory (L0/L1/L2/L4 as policy dictates)
        await self._unified_memory.ingest_event(memory_event.to_dict())

        # 3. Notify timeline adapter (for viewport/query read model)
        if self._timeline_adapter is not None:
            await self._timeline_adapter.on_sensor_output(event_id, output, metadata)

        # 4. Process knowledge graph relations
        relation_count = 0
        if metadata and metadata.relation_candidates and allowed_edge_whitelist:
            relation_count = await self._process_relations(
                event_id, output, metadata, sensor, allowed_edge_whitelist,
            )

        # 5. Update sensor state (fingerprint tracking)
        if self._state_store is not None:
            fp = sensor.source_item_version_fingerprint(output.to_dict())
            await self._state_store.add_fingerprints(sensor.sensor_id, {fp})

        return SensorIngestionResult(
            event_id=event_id,
            ingested=True,
            stats={"relation_count": relation_count},
        )

    def _build_memory_event(
        self,
        event_id: str,
        output: SensorOutput,
        policy: Any,
    ) -> MemoryEvent:
        """Build a MemoryEvent from SensorOutput + SensorMemoryPolicy."""
        content = output.summary or output.title or ""
        if not content:
            block_text = " ".join(
                b.value.strip()
                for b in output.content_blocks
                if b.kind == "text" and b.value.strip()
            )
            if block_text:
                content = block_text

        return MemoryEvent(
            event_id=event_id,
            correlation_id=event_id,
            timestamp=output.occurred_at,
            created_at=output.captured_at,
            event_type="SENSOR_EVENT",
            source=output.source_type,
            source_item_id=output.source_item_id,
            memory_domain=MemoryDomain.from_value(policy.memory_domain),
            ingest_target=IngestTarget.from_value(policy.ingest_target),
            cognition_eligible=policy.cognition_eligible,
            tom_depth=TomDepth.from_value(policy.tom_depth),
            retention_class=RetentionClass.from_value(policy.retention_class),
            session_id=None,
            turn_id=None,
            user_id=None,
            task_id=None,
            content=content,
            author_type=policy.author_type,
            content_type=policy.content_type,
            importance_score=policy.importance_bias,
            level=EventLevel.INFO.value,
            media_path=output.raw_payload_ref,
        )

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
