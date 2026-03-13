"""Timeline sensor for Screen Time data."""
from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timedelta, date
from typing import Any

from magi.timeline import SensorSyncContext, SensorSyncResult, TimelineContentBlock, TimelineEvent
from magi.timeline.sensors.base import TimelineSensorBase

from .exceptions import PlatformNotSupportedError
from .normalizers import normalize_daily_screen_time
from .reader import ScreenTimeReader
from .types import DailyScreenTime, AppUsage


class ScreenTimeTimelineSensor(TimelineSensorBase):
    """Timeline sensor for Screen Time data."""

    sensor_id = "timeline.screen_time"
    display_name = "Screen Time"
    source_type = "screen_time"
    polling_mode = "interval"
    default_interval = 3600  # 1 hour
    update_key_fields = ("date",)
    relation_edge_whitelist = ("TRACKed", "used")
    supports_pull_sync = True

    def __init__(self, *, retention_mode=None, reader=None):
        super().__init__(retention_mode=retention_mode)
        self._reader = reader

    @property
    def reader(self) -> ScreenTimeReader:
        """Get or create ScreenTimeReader instance (lazy initialization)."""
        if self._reader is None:
            if sys.platform != "darwin":
                raise PlatformNotSupportedError()
            self._reader = ScreenTimeReader()
        return self._reader

    def source_item_identity(self, item: dict) -> str:
        """Generate unique identity for a source item."""
        date_str = item.get("date", "")
        if isinstance(date_str, date):
            date_str = date_str.isoformat()
        return f"screen_time_{date_str}"

    def source_item_version_fingerprint(self, item: dict) -> str:
        """Generate version fingerprint for change detection."""
        version_parts = [
            str(item.get("date", "")),
            str(item.get("total_duration", 0)),
            str(len(item.get("app_usages", []))),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect screen time data from SQLite database."""
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )

        # Get settings
        lookback_days = sensor_settings.get("lookback_days", 30)

        # Determine date range
        now = datetime.now().date()
        if context.last_cursor:
            try:
                last_date_str = context.last_cursor
                start_date = datetime.strptime(last_date_str).date()
            except (ValueError, TypeError):
                start_date = now - timedelta(days=lookback_days)
        else:
            # Initial sync - get last 30 days
            start_date = now - timedelta(days=lookback_days)

        end_date = now

        # Read screen time data
        try:
            daily_data = self.reader.read_daily_screen_time(start_date, end_date)
        except Exception as e:
            return SensorSyncResult(
                items=[],
                next_cursor=None,
                watermark_ts=time.time(),
                stats={
                    "count": 0,
                    "error": str(e),
                },
            )

        # Convert to items
        items = []
        for daily in daily_data:
            item = {
                "date": daily.date.isoformat(),
                "total_duration": daily.total_duration,
                "app_usages": [
                    {
                        "bundle_id": app.bundle_id,
                        "app_name": app.app_name,
                        "usage_seconds": app.usage_seconds,
                        "category": app.category,
                    }
                    for app in daily.app_usages
                ],
            }
            items.append(item)

        # Sort items by date (most recent first)
        items.sort(key=lambda x: x.get("date", ""), reverse=True)

        # Determine next cursor
        next_cursor = None
        watermark_ts = context.last_success_at or time.time()

        if items:
            min_date = min(item.get("date") for item in items)
            next_cursor = str(min_date)
            watermark_ts = max(item.get("date") for item in items)

        return SensorSyncResult(
            items=items,
            next_cursor=next_cursor,
            watermark_ts=watermark_ts,
            stats={
                "count": len(items),
            },
        )

    async def build_timeline_event(self, item: dict) -> TimelineEvent:
        """Build a TimelineEvent from a screen time item."""
        # Normalize - pass item dict directly
        normalized_data = normalize_daily_screen_time(item, self)

        # Parse date for occurred_at
        date_str = item.get("date", "")
        if isinstance(date_str, str):
            occurred_at = datetime.fromisoformat(date_str).timestamp()
        else:
            occurred_at = time.time()

        return TimelineEvent(
            event_id=normalized_data["event_id"],
            source_type=self.source_type,
            source_item_id=normalized_data["source_item_id"],
            occurred_at=occurred_at,
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
