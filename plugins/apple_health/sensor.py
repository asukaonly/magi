"""Timeline sensor for Apple Health data."""
from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from magi.awareness import SensorBase, ContentBlock, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult

from .exceptions import PlatformNotSupportedError
from .normalizers import NORMALIZERS
from .reader import HealthKitReader
from .types import HEALTH_DATA_TYPES, HealthDataType, get_default_enabled_types


class AppleHealthTimelineSensor(SensorBase):
    """Timeline sensor for Apple Health data."""

    sensor_id = "timeline.apple_health"
    display_name = "Apple Health"
    source_type = "apple_health"
    polling_mode = "interval"
    default_interval = 60
    update_key_fields = ("data_type", "date", "session_id")
    relation_edge_whitelist = ("TRACKED", "EXERCISED")
    supports_pull_sync = True

    memory_policy = SensorMemoryPolicy(
        retention_class="permanent",
        cognition_eligible=True,
        importance_bias=0.6,
    )

    def __init__(self, *, retention_mode=None, enabled_types=None, reader=None):
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
        self.enabled_types = enabled_types or get_default_enabled_types()
        self._reader = reader

    @property
    def reader(self) -> HealthKitReader:
        """Get or create HealthKitReader instance (lazy initialization)."""
        if self._reader is None:
            if sys.platform != "darwin":
                raise PlatformNotSupportedError()
            self._reader = HealthKitReader()
        return self._reader

    def source_item_identity(self, item: dict) -> str:
        """Generate unique identity for a source item."""
        data_type = item.get("data_type", "")
        date = item.get("date")
        session_id = item.get("session_id")

        # Format: "apple_health_{data_type}_{date_or_session_id}"
        if date:
            return f"apple_health_{data_type}_{date}"
        elif session_id:
            return f"apple_health_{data_type}_{session_id}"
        else:
            return f"apple_health_{data_type}_{int(time.time())}"

    def source_item_version_fingerprint(self, item: dict) -> str:
        """Generate version fingerprint for change detection."""
        # Use all key fields plus value for fingerprint
        version_parts = [
            str(item.get("data_type", "")),
            str(item.get("date", "")),
            str(item.get("session_id", "")),
            str(item.get("value", 0)),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect health data items from all enabled types."""
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )

        # Update enabled_types from settings if provided
        if "enabled_types" in sensor_settings:
            enabled_keys = sensor_settings["enabled_types"]
            self.enabled_types = [health_type for health_type in self.enabled_types
                               if health_type.key in enabled_keys]

        items = []

        # Get current date range based on context
        now = datetime.now()
        if context.last_cursor:
            # Convert cursor to datetime
            try:
                last_timestamp = float(context.last_cursor)
                start_date = datetime.fromtimestamp(last_timestamp)
            except (ValueError, TypeError):
                start_date = now
        else:
            # Initial sync - get last 7 days by default
            start_date = now - timedelta(days=7)

        end_date = now

        # For each enabled type:
        # 1. Check authorization status
        # 2. Collect based on aggregation type (daily/sample/session)
        type_keys = [health_type.key for health_type in self.enabled_types]
        auth_status = self.reader.get_authorization_status(type_keys)

        for health_type in self.enabled_types:
            type_key = health_type.key
            type_auth = auth_status.get(type_key, "unavailable")

            if type_auth != "sharing_authorized":
                # Skip unauthorized types
                continue

            # Collect based on aggregation type
            if health_type.aggregation == "daily":
                daily_items = self.reader.read_daily_aggregate(
                    type_key,
                    start_date,
                    end_date
                )
                items.extend(daily_items)
            elif health_type.aggregation == "sample":
                sample_items = self.reader.read_samples(
                    type_key,
                    start_date,
                    end_date,
                    limit=max(1, context.limit) // len(self.enabled_types) if len(self.enabled_types) > 1 else context.limit
                )
                items.extend(sample_items)
            elif health_type.aggregation == "session":
                if type_key == "sleep":
                    session_items = self.reader.read_sessions(type_key, start_date, end_date)
                    items.extend(session_items)
                elif type_key == "workout":
                    workout_items = self.reader.read_workouts(start_date, end_date)
                    items.extend(workout_items)

        # Sort items by timestamp
        def get_timestamp(item):
            date_str = item.get("date")
            if date_str:
                try:
                    return datetime.fromisoformat(date_str).timestamp()
                except (ValueError, TypeError):
                    return 0
            return float(item.get("timestamp", time.time()))

        items.sort(key=get_timestamp, reverse=True)

        # Determine next cursor
        next_cursor = None
        watermark_ts = context.last_success_at or time.time()

        if items:
            # Use the earliest date as next cursor
            def get_timestamp(item):
                date_str = item.get("date")
                if date_str:
                    try:
                        return datetime.fromisoformat(date_str).timestamp()
                    except (ValueError, TypeError):
                        return 0
                return 0

            min_timestamp = min(get_timestamp(item) for item in items)
            next_cursor = str(min_timestamp)
            watermark_ts = max(get_timestamp(item) for item in items)

        return SensorSyncResult(
            items=items,
            next_cursor=next_cursor,
            watermark_ts=watermark_ts,
            stats={
                "count": len(items),
                "enabled_types": [ht.key for ht in self.enabled_types],
                "authorized_types": [k for k, v in auth_status.items() if v == "sharing_authorized"],
                "initial_sync": context.last_cursor is None,
            },
        )

    def request_activation_authorization(self, field_values: dict[str, Any] | None = None) -> dict[str, Any]:
        """Request HealthKit authorization for the selected data types."""
        selected_values = field_values or {}
        requested_types = [
            type_key
            for type_key in HEALTH_DATA_TYPES
            if bool(selected_values.get(f"sensors.apple_health.types.{type_key}", False))
        ]
        if not requested_types:
            requested_types = [health_type.key for health_type in self.enabled_types]

        if not requested_types:
            return {
                "authorized": False,
                "requested_types": [],
                "granted_types": [],
                "denied_types": [],
                "message": "No Apple Health data types were selected for authorization.",
            }

        result = self.reader.request_authorization(requested_types)
        granted_types = [type_key for type_key in requested_types if result.get(type_key) is True]
        denied_types = [type_key for type_key in requested_types if result.get(type_key) is not True]
        return {
            "authorized": len(denied_types) == 0,
            "requested_types": requested_types,
            "granted_types": granted_types,
            "denied_types": denied_types,
            "message": (
                None
                if not denied_types
                else "Apple Health authorization was not granted for all selected data types."
            ),
        }

    async def build_output(self, item: dict) -> SensorOutput:
        """Build a SensorOutput from a health data item."""
        data_type = item.get("data_type", "")

        # Find the right normalizer
        normalizer = NORMALIZERS.get(data_type)

        if normalizer:
            # Use the normalizer to build event data
            normalized_data = normalizer(item, self)
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
        else:
            # Fall back to generic event
            data_type_display = self.t(f"data_types.{data_type}", fallback=data_type.replace("_", " ").title())
            title = self.t("content_blocks.health_data", data_type=data_type_display)
            summary = str(item.get("value", "Unknown"))

            # Handle date conversion
            date_str = item.get("date")
            if date_str:
                try:
                    occurred_at = datetime.fromisoformat(date_str).timestamp()
                except (ValueError, TypeError):
                    occurred_at = time.time()
            else:
                occurred_at = time.time()

            return self._build_output(
                source_item_id=self.source_item_identity(item),
                title=title,
                summary=summary,
                occurred_at=occurred_at,
                content_blocks=[
                    ContentBlock(kind="text", value=str(item))
                ],
                tags=["apple_health", data_type],
                provenance={
                    "sensor_id": self.sensor_id,
                    "data_type": data_type,
                    "raw_item": item,
                },
                domain_payload={"retention_mode": self.retention_mode},
            )
