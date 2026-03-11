"""Timeline sensor for manual journal entries."""
from __future__ import annotations

from ..contracts import TimelineContentBlock, TimelineEvent
from .base import TimelineSensorBase


class ManualJournalTimelineSensor(TimelineSensorBase):
    sensor_id = "timeline.manual_journal"
    display_name = "Manual Journal"
    source_type = "manual_journal"
    polling_mode = "manual"
    default_interval = 1
    update_key_fields = ("entry_id", "updated_at", "text")
    relation_edge_whitelist = ("MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "CREATED", "RELATED_TO")

    @property
    def default_retention_mode(self) -> str:
        return "retain_raw"

    async def build_timeline_event(self, item: dict[str, object]) -> TimelineEvent:
        source_item_id = str(item.get("entry_id") or item.get("id") or "manual-entry")
        text = str(item.get("text", ""))
        image_refs = [str(image_ref) for image_ref in item.get("image_refs", [])]
        content_blocks = [TimelineContentBlock(kind="text", value=text)]
        content_blocks.extend(TimelineContentBlock(kind="image", value=image_ref) for image_ref in image_refs)
        return self._build_event(
            source_item_id=source_item_id,
            title=str(item.get("title") or "Manual journal"),
            summary=text[:140] if text else str(item.get("title") or "Manual journal"),
            occurred_at=float(item.get("occurred_at") or 0.0),
            raw_payload_ref=str(item.get("raw_payload_ref")) if item.get("raw_payload_ref") else None,
            content_blocks=content_blocks,
            tags=["manual_journal"],
        )
