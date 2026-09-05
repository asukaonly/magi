"""Build the timeline read model from host-rendered source projections.

Relocated from ``magi.awareness.source_projection`` to invert the
awareness->timeline coupling: timeline events are a timeline-layer concern, so
the projection that produces a :class:`TimelineEvent` lives here and reaches
*down* into awareness for the source output/projection inputs.
"""

from __future__ import annotations

from .contracts import TimelineContentBlock, TimelineEvent
from ..awareness.source_output import SourceOutput, SourceOutputMetadata
from ..awareness.source_projection import SourceProjection


def build_source_timeline_event(
    event_id: str,
    output: SourceOutput,
    projection: SourceProjection,
    metadata: SourceOutputMetadata | None = None,
) -> TimelineEvent:
    """Build the timeline read model from a host-rendered source projection."""
    extra_entities = metadata.entities if metadata else []
    extra_tags = metadata.tags if metadata else []

    return TimelineEvent(
        event_id=event_id,
        source_type=output.source_type,
        source_item_id=output.source_item_id,
        occurred_at=output.occurred_at,
        captured_at=output.captured_at,
        title=projection.title,
        summary=projection.summary,
        retention_mode=output.domain_payload.get("retention_mode", "analyze_only"),
        raw_payload_ref=output.raw_payload_ref,
        content_blocks=[
            TimelineContentBlock(
                kind=block.kind,
                value=block.value,
                mime_type=block.mime_type,
            )
            for block in output.content_blocks
        ],
        entities=output.entities + extra_entities,
        tags=list(dict.fromkeys(output.tags + extra_tags)),
        privacy_labels=output.domain_payload.get("privacy_labels", []),
        processing_status={
            "stored": True,
            "analyzed": bool(metadata and (metadata.relation_candidates or metadata.fact_hints)),
        },
        provenance=output.provenance,
    )


__all__ = [
    "build_source_timeline_event",
]
