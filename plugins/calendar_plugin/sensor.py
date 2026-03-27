"""Timeline sensor for Calendar data."""
from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from magi.awareness import SensorBase, ContentBlock, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult
from magi.core.logger import get_logger

from .exceptions import PlatformNotSupportedError
from .normalizers import normalize_calendar_event
from .reader import EventKitReader
from .types import CalendarEvent, Participant

logger = get_logger(__name__)


class CalendarTimelineSensor(SensorBase):
    """Timeline sensor for Calendar data."""

    sensor_id = "timeline.calendar"
    display_name = "Calendar"
    source_type = "calendar"
    polling_mode = "interval"
    default_interval = 1800  # 30 minutes
    update_key_fields = ("event_id", "start_time")
    relation_edge_whitelist = ("SCHEDULED", "ATTENDED")
    supports_pull_sync = True

    memory_policy = SensorMemoryPolicy(
        retention_class="permanent",
        cognition_eligible=True,
        importance_bias=0.7,
    )

    def __init__(self, *, retention_mode=None, reader=None):
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
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

    def request_activation_authorization(self, field_values: dict[str, Any] | None = None) -> dict[str, Any]:
        """Request EventKit authorization for calendar access."""
        del field_values
        authorized = self.reader.request_authorization()
        return {
            "authorized": bool(authorized),
            "requested_types": ["calendar"],
            "granted_types": ["calendar"] if authorized else [],
            "denied_types": [] if authorized else ["calendar"],
            "message": None if authorized else "Calendar access was not granted.",
        }

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
        selected_calendar_ids = sensor_settings.get("selected_calendar_ids", [])

        # Determine date range
        now = datetime.now()
        lookback_floor = now - timedelta(days=lookback_days)
        if context.last_cursor:
            try:
                last_timestamp = float(context.last_cursor)
                latest_seen_at = datetime.fromtimestamp(last_timestamp)
                start_date = max(latest_seen_at - timedelta(days=1), lookback_floor)
            except (ValueError, TypeError):
                start_date = lookback_floor
        else:
            # Initial sync - get last 30 days by default
            start_date = lookback_floor

        end_date = now + timedelta(days=recurring_expansion_days)

        # Check authorization
        auth_status = self.reader.get_authorization_status()
        if auth_status != "authorized":
            logger.warning(
                "Skipping calendar sync because calendar authorization is unavailable",
                authorization_status=auth_status,
                source_type=self.source_type,
                manual=context.manual,
                initial_sync=context.last_cursor is None,
            )
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
        events = self.reader.read_events(
            start_date,
            end_date,
            selected_calendar_ids if isinstance(selected_calendar_ids, list) and selected_calendar_ids else None,
        )
        logger.info(
            "Calendar sensor collected events",
            source_type=self.source_type,
            manual=context.manual,
            initial_sync=context.last_cursor is None,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            event_count=len(events),
        )

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
            logger.info(
                "Calendar sensor prepared source item",
                event_id=item["event_id"],
                title=item["title"],
                start_time=item["start_time"],
                end_time=item["end_time"],
                location=item["location"],
                has_notes=bool(item["notes"]),
                participant_count=len(item["participants"]),
            )

        # Sort items by start time
        items.sort(key=lambda x: x.get("start_time", 0), reverse=True)

        # Determine next cursor and watermark
        next_cursor = None
        watermark_ts = context.last_success_at or time.time()

        if items:
            latest_timestamp = max(item.get("start_time", time.time()) for item in items)
            next_cursor = str(latest_timestamp)
            watermark_ts = latest_timestamp

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

    async def build_output(self, item: dict) -> SensorOutput:
        """Build a SensorOutput from a calendar event item."""
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
        logger.info(
            "Calendar sensor built output",
            event_id=event.event_id,
            source_item_id=normalized_data["source_item_id"],
            output_title=normalized_data["title"],
            output_summary=normalized_data["summary"],
            content_block_count=len(normalized_data["content_blocks"]),
            tag_count=len(normalized_data["tags"]),
        )

        return self._build_output(
            source_item_id=normalized_data["source_item_id"],
            title=normalized_data["title"],
            summary=normalized_data["summary"],
            occurred_at=normalized_data["occurred_at"],
            content_blocks=[
                ContentBlock(kind=block["kind"], value=block["value"])
                for block in normalized_data["content_blocks"]
            ],
            tags=normalized_data["tags"],
            provenance={
                "sensor_id": self.sensor_id,
                **normalized_data["provenance"],
            },
            domain_payload={"retention_mode": self.retention_mode},
        )
