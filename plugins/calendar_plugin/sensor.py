"""Timeline sensor for Calendar data."""
from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from magi.timeline import SensorSyncContext, SensorSyncResult, TimelineContentBlock, TimelineEvent
from magi.timeline.sensors.base import TimelineSensorBase

from .exceptions import PlatformNotSupportedError
from .normalizers import normalize_calendar_event
from .reader import EventKitReader
from .types import CalendarEvent, Participant


class CalendarTimelineSensor(TimelineSensorBase):
    """Timeline sensor for Calendar data."""

    sensor_id = "timeline.calendar"
    display_name = "Calendar"
    source_type = "calendar"
    polling_mode = "interval"
    default_interval = 1800  # 30 minutes
    update_key_fields = ("event_id", "start_time")
    relation_edge_whitelist = ("SCHEDULED", "ATTENDED")
    supports_pull_sync = True

    def __init__(self, *, retention_mode=None, reader=None):
        super().__init__(retention_mode=retention_mode)
        self._reader = reader

    @property
    def reader(self) -> EventKitReader:
        """Get or create EventKitReader instance (lazy initialization)."""
        if self._reader is None:
            if sys.platform != "darwin":
                raise PlatformNotSupportedError()
            self._reader = EventKitReader()
        return self._reader

    def source_item_identity(self, item: dict) -> str:
        """Generate unique identity for a source item."""
        event_id = item.get("event_id", "")
        return f"calendar_{event_id}"

    def source_item_version_fingerprint(self, item: dict) -> str:
        """Generate version fingerprint for change detection."""
        version_parts = [
            str(item.get("event_id", "")),
            str(item.get("title", "")),
            str(item.get("start_time", "")),
            str(item.get("end_time", "")),
            str(item.get("location", "")),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect calendar events from EventKit."""
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )

        # Get settings
        lookback_days = sensor_settings.get("lookback_days", 30)
        recurring_expansion_days = sensor_settings.get("recurring_expansion_days", 30)

        # Determine date range
        now = datetime.now()
        if context.last_cursor:
            try:
                last_timestamp = float(context.last_cursor)
                start_date = datetime.fromtimestamp(last_timestamp)
            except (ValueError, TypeError):
                start_date = now - timedelta(days=lookback_days)
        else:
            # Initial sync - get last 30 days by default
            start_date = now - timedelta(days=lookback_days)

        end_date = now + timedelta(days=recurring_expansion_days)

        # Check authorization
        auth_status = self.reader.get_authorization_status()
        if auth_status != "authorized":
            return SensorSyncResult(
                items=[],
                next_cursor=None,
                watermark_ts=time.time(),
                stats={
                    "count": 0,
                    "authorization_status": auth_status,
                    "initial_sync": context.last_cursor is None,
                },
            )

        # Read events
        events = self.reader.read_events(start_date, end_date)

        # Convert to items
        items = []
        for event in events:
            item = {
                "event_id": event.event_id,
                "title": event.title,
                "start_time": event.start_time.timestamp(),
                "end_time": event.end_time.timestamp(),
                "is_all_day": event.is_all_day,
                "location": event.location,
                "notes": event.notes,
                "calendar_name": event.calendar_name,
                "calendar_color": event.calendar_color,
                "participants": [
                    {"name": p.name, "email": p.email, "status": p.status}
                    for p in event.participants
                ],
                "is_recurring": event.is_recurring,
                "recurrence_rule": event.recurrence_rule,
                "url": event.url,
            }
            items.append(item)

        # Sort items by start time
        items.sort(key=lambda x: x.get("start_time", 0), reverse=True)

        # Determine next cursor and watermark
        next_cursor = None
        watermark_ts = context.last_success_at or time.time()

        if items:
            min_timestamp = min(item.get("start_time", time.time()) for item in items)
            next_cursor = str(min_timestamp)
            watermark_ts = max(item.get("start_time", time.time()) for item in items)

        return SensorSyncResult(
            items=items,
            next_cursor=next_cursor,
            watermark_ts=watermark_ts,
            stats={
                "count": len(items),
                "authorization_status": auth_status,
                "initial_sync": context.last_cursor is None,
            },
        )

    async def build_timeline_event(self, item: dict) -> TimelineEvent:
        """Build a TimelineEvent from a calendar event item."""
        # Reconstruct CalendarEvent from item dict
        start_ts = item.get("start_time", time.time())
        end_ts = item.get("end_time", time.time())

        event = CalendarEvent(
            event_id=item.get("event_id", ""),
            title=item.get("title", ""),
            start_time=datetime.fromtimestamp(start_ts),
            end_time=datetime.fromtimestamp(end_ts),
            is_all_day=item.get("is_all_day", False),
            location=item.get("location"),
            notes=item.get("notes"),
            calendar_name=item.get("calendar_name", ""),
            calendar_color=item.get("calendar_color", ""),
            participants=[
                Participant(
                    name=p.get("name", ""),
                    email=p.get("email"),
                    status=p.get("status", "pending")
                )
                for p in item.get("participants", [])
            ],
            is_recurring=item.get("is_recurring", False),
            recurrence_rule=item.get("recurrence_rule"),
            url=item.get("url"),
        )

        # Normalize
        normalized_data = normalize_calendar_event(event, self)

        return TimelineEvent(
            event_id=normalized_data["event_id"],
            source_type=self.source_type,
            source_item_id=normalized_data["source_item_id"],
            occurred_at=normalized_data["occurred_at"],
            captured_at=time.time(),
            title=normalized_data["title"],
            summary=normalized_data["summary"],
            retention_mode=self.retention_mode,
            raw_payload_ref=None,
            content_blocks=[
                TimelineContentBlock(kind=block["kind"], value=block["value"])
                for block in normalized_data["content_blocks"]
            ],
            tags=normalized_data["tags"],
            processing_status={"stored": False, "analyzed": False},
            provenance={
                "sensor_id": self.sensor_id,
                **normalized_data["provenance"],
            },
        )