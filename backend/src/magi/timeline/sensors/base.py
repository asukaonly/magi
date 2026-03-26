"""Base contracts for timeline sensors.

TimelineSensorBase is a backward-compatible adapter that extends the new
SensorBase (L9) while preserving the legacy build_timeline_event / _build_event /
extract_candidates API for existing sensor plugins. This allows all 8 sensor
plugins to work unchanged during Phase 1 of the sensor-timeline decoupling.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from typing import Any, Optional

from ...awareness.sensor_base import SensorBase
from ...awareness.sensor_output import ContentBlock, SensorMemoryPolicy, SensorOutput, SensorOutputMetadata
from ...awareness.sensor_sync import SensorSyncContext, SensorSyncResult
from ..contracts import TimelineContentBlock, TimelineEvent


class TimelineSensorBase(SensorBase):
    """Backward-compatible adapter for timeline sensors.

    Extends the new ``SensorBase`` and bridges the legacy
    ``build_timeline_event`` / ``extract_candidates`` API so existing
    sensor plugins require zero code changes during Phase 1.
    """

    sensor_id: str = "timeline.base"
    display_name: str = "Timeline Source"
    source_type: str = "unknown"

    # Legacy timeline-specific class attributes
    supports_retention_modes: tuple[str, ...] = ("retain_raw", "analyze_only")
    supports_content_blocks: tuple[str, ...] = ("text",)

    def __init__(
        self,
        *,
        retention_mode: Optional[str] = None,
        source_path: Optional[str] = None,
        fetch_page_content: bool = False,
    ) -> None:
        super().__init__()
        self.retention_mode = retention_mode or self.default_retention_mode
        self.source_path = source_path
        self.fetch_page_content = fetch_page_content

    @property
    def default_retention_mode(self) -> str:
        return "analyze_only"

    # ------------------------------------------------------------------
    # Compatibility bridge: SensorBase.build_output → build_timeline_event
    # ------------------------------------------------------------------

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        """Bridge: convert legacy TimelineEvent to SensorOutput."""
        event = await self.build_timeline_event(item)
        return SensorOutput(
            source_type=event.source_type,
            source_item_id=event.source_item_id,
            occurred_at=event.occurred_at,
            captured_at=event.captured_at,
            title=event.title,
            summary=event.summary,
            content_blocks=[
                ContentBlock(kind=b.kind, value=b.value, mime_type=b.mime_type)
                for b in event.content_blocks
            ],
            raw_payload_ref=event.raw_payload_ref,
            tags=event.tags,
            entities=event.entities,
            provenance=event.provenance,
            domain_payload={
                "retention_mode": event.retention_mode,
                "privacy_labels": event.privacy_labels,
                "processing_status": event.processing_status,
            },
        )

    async def extract_metadata(self, item: dict[str, Any]) -> SensorOutputMetadata:
        """Bridge: convert legacy extract_candidates to typed metadata."""
        raw = await self.extract_candidates(item)
        return SensorOutputMetadata(
            entities=list(raw.get("entities", [])),
            tags=list(raw.get("tags", [])),
            relation_candidates=list(raw.get("relation_candidates", [])),
        )

    # ------------------------------------------------------------------
    # Legacy API (kept for existing sensor plugins)
    # ------------------------------------------------------------------

    @abstractmethod
    async def build_timeline_event(self, item: dict[str, Any]) -> TimelineEvent:
        """Convert a source item into a normalized timeline event."""

    async def resolve_retention_assets(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        _ = item
        return []

    async def extract_candidates(self, item: dict[str, Any]) -> dict[str, Any]:
        _ = item
        return {"entities": [], "tags": [], "relation_candidates": []}

    def _build_event(
        self,
        *,
        source_item_id: str,
        title: str,
        summary: str,
        occurred_at: Optional[float] = None,
        raw_payload_ref: Optional[str] = None,
        content_blocks: Optional[list[TimelineContentBlock]] = None,
        tags: Optional[list[str]] = None,
        provenance: Optional[dict[str, Any]] = None,
    ) -> TimelineEvent:
        now = time.time()
        event_id = f"{self.source_type}:{source_item_id}"
        return TimelineEvent(
            event_id=event_id,
            source_type=self.source_type,
            source_item_id=source_item_id,
            occurred_at=float(occurred_at or now),
            captured_at=now,
            title=title,
            summary=summary,
            retention_mode=self.retention_mode,
            raw_payload_ref=raw_payload_ref,
            content_blocks=list(content_blocks or []),
            tags=list(tags or []),
            processing_status={"stored": False, "analyzed": False},
            provenance=provenance or {"sensor_id": self.sensor_id},
        )
