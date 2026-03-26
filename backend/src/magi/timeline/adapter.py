"""Timeline adapter — converts SensorOutput into TimelineEvent read models (L12)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..awareness.sensor_output import SensorOutput, SensorOutputMetadata
from .contracts import TimelineContentBlock, TimelineEvent

if TYPE_CHECKING:
    from .service import TimelineService


class TimelineAdapter:
    """Converts SensorOutput into TimelineEvent for timeline read models.

    The adapter owns the SensorOutput → TimelineEvent mapping. It writes
    to the timeline read model (via TimelineService) but does NOT re-ingest
    into memory — that is handled by the SensorIngestionGateway.
    """

    def __init__(self, timeline_service: TimelineService) -> None:
        self._service = timeline_service

    async def on_sensor_output(
        self,
        event_id: str,
        output: SensorOutput,
        metadata: SensorOutputMetadata | None = None,
    ) -> None:
        """Build a TimelineEvent and store it in the timeline read model."""
        timeline_event = self._build_timeline_event(event_id, output, metadata)
        # Use existing upsert path for now — this stores in memory again which is
        # redundant but safe (idempotent by event_id). In Phase 3, this will be
        # replaced by a dedicated timeline read-model store.
        await self._service.upsert_event(timeline_event)

    @staticmethod
    def _build_timeline_event(
        event_id: str,
        output: SensorOutput,
        metadata: SensorOutputMetadata | None = None,
    ) -> TimelineEvent:
        """Map SensorOutput → TimelineEvent."""
        extra_entities = metadata.entities if metadata else []
        extra_tags = metadata.tags if metadata else []

        return TimelineEvent(
            event_id=event_id,
            source_type=output.source_type,
            source_item_id=output.source_item_id,
            occurred_at=output.occurred_at,
            captured_at=output.captured_at,
            title=output.title,
            summary=output.summary,
            retention_mode=output.domain_payload.get("retention_mode", "analyze_only"),
            raw_payload_ref=output.raw_payload_ref,
            content_blocks=[
                TimelineContentBlock(kind=b.kind, value=b.value, mime_type=b.mime_type)
                for b in output.content_blocks
            ],
            entities=output.entities + extra_entities,
            tags=list(dict.fromkeys(output.tags + extra_tags)),
            privacy_labels=output.domain_payload.get("privacy_labels", []),
            processing_status={
                "stored": True,
                "analyzed": bool(metadata and metadata.relation_candidates),
            },
            provenance=output.provenance,
        )
