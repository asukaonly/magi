"""Timeline sensor for chat conversation facts."""
from __future__ import annotations

from ..contracts import TimelineContentBlock, TimelineEvent
from .base import TimelineSensorBase


class ChatTimelineSensor(TimelineSensorBase):
    sensor_id = "timeline.chat"
    display_name = "Chat"
    source_type = "chat"
    polling_mode = "watch"
    default_interval = 1
    update_key_fields = ("turn_id", "message", "timestamp")
    relation_edge_whitelist = ("MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "INTERACTED_WITH")

    async def build_timeline_event(self, item: dict[str, object]) -> TimelineEvent:
        message = str(item.get("message", ""))
        turn_id = str(item.get("turn_id") or item.get("message_id") or "chat")
        return self._build_event(
            source_item_id=turn_id,
            title="Chat message",
            summary=message[:140],
            occurred_at=float(item.get("timestamp") or 0.0),
            content_blocks=[TimelineContentBlock(kind="text", value=message)],
            tags=["chat"],
        )

    async def extract_candidates(self, item: dict[str, object]) -> dict[str, object]:
        return {
            "entities": list(item.get("entities", [])),
            "tags": ["chat"],
            "relation_candidates": list(item.get("relation_candidates", [])),
        }
