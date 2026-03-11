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
        user_message = str(item.get("user_message") or item.get("message") or "")
        assistant_message = str(item.get("assistant_message") or item.get("response") or "")
        turn_id = str(item.get("turn_id") or item.get("message_id") or "chat")
        content_blocks = []
        if user_message:
            content_blocks.append(TimelineContentBlock(kind="text", value=f"User: {user_message}"))
        if assistant_message:
            content_blocks.append(TimelineContentBlock(kind="text", value=f"Assistant: {assistant_message}"))
        if not content_blocks:
            content_blocks.append(TimelineContentBlock(kind="text", value=str(item.get("message", ""))))
        summary_source = user_message or assistant_message or str(item.get("message", ""))
        return self._build_event(
            source_item_id=turn_id,
            title="Chat turn",
            summary=summary_source[:140],
            occurred_at=float(item.get("timestamp") or 0.0),
            content_blocks=content_blocks,
            tags=["chat"],
            provenance={
                "sensor_id": self.sensor_id,
                "user_id": str(item.get("user_id") or ""),
                "session_id": str(item.get("session_id") or ""),
                "turn_id": turn_id,
                "orchestration_id": str(item.get("orchestration_id") or ""),
            },
        )

    async def extract_candidates(self, item: dict[str, object]) -> dict[str, object]:
        return {
            "entities": list(item.get("entities", [])),
            "tags": ["chat"],
            "relation_candidates": list(item.get("relation_candidates", [])),
        }
