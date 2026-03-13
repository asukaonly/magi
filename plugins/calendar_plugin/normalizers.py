"""Normalization helpers for Calendar timeline ingestion."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .types import CalendarEvent, Participant


def normalize_calendar_event(event: CalendarEvent, sensor: Any) -> dict[str, Any]:
    """Normalize a calendar event into timeline event data.

    Args:
        event: CalendarEvent to normalize
        sensor: The sensor instance (for sensor_id)

    Returns:
        Dictionary with normalized event data
    """
    # Build title
    if event.is_all_day:
        title = f"全天：{event.title}"
    else:
        start_str = event.start_time.strftime("%H:%M")
        end_str = event.end_time.strftime("%H:%M")
        title = f"{event.title} ({start_str}-{end_str})"

    # Build summary
    summary_parts = [event.title]
    if event.location:
        summary_parts.append(f"地点：{event.location}")
    summary = " | ".join(summary_parts)

    # Build content blocks
    content_blocks = []

    # Time block
    if event.is_all_day:
        content_blocks.append({
            "kind": "text",
            "value": f"时间：全天 ({event.start_time.strftime('%Y-%m-%d')})"
        })
    else:
        time_str = f"时间：{event.start_time.strftime('%Y-%m-%d %H:%M')} - {event.end_time.strftime('%H:%M')}"
        content_blocks.append({
            "kind": "text",
            "value": time_str
        })

    # Location block
    if event.location:
        content_blocks.append({
            "kind": "text",
            "value": f"地点：{event.location}"
        })

    # Calendar block
    content_blocks.append({
        "kind": "text",
        "value": f"日历：{event.calendar_name}"
    })

    # Participants block
    if event.participants:
        participant_names = ", ".join(p.name for p in event.participants)
        content_blocks.append({
            "kind": "text",
            "value": f"参与者：{participant_names}"
        })

    # Notes block
    if event.notes:
        content_blocks.append({
            "kind": "text",
            "value": f"备注：{event.notes}"
        })

    # Recurring info
    if event.is_recurring:
        content_blocks.append({
            "kind": "text",
            "value": f"重复：{event.recurrence_rule or '是'}"
        })

    # Build tags
    tags = ["calendar", "event"]
    if event.is_recurring:
        tags.append("recurring")
    if event.is_all_day:
        tags.append("all_day")

    # Build provenance
    provenance = {
        "sensor_id": sensor.sensor_id,
        "event_id": event.event_id,
        "calendar_name": event.calendar_name,
        "calendar_color": event.calendar_color,
        "is_recurring": event.is_recurring,
        "is_all_day": event.is_all_day,
    }
    if event.url:
        provenance["url"] = event.url
    if event.recurrence_rule:
        provenance["recurrence_rule"] = event.recurrence_rule

    return {
        "event_id": f"calendar_{event.event_id}",
        "source_type": "calendar",
        "source_item_id": f"calendar_{event.event_id}",
        "occurred_at": event.start_time.timestamp(),
        "title": title,
        "summary": summary,
        "content_blocks": content_blocks,
        "tags": tags,
        "provenance": provenance,
    }