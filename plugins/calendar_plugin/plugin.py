"""Calendar timeline plugin."""
from __future__ import annotations

import sys
from typing import Any

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .reader import EventKitReader
from .sensor import CalendarTimelineSensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_interval_minutes": 30,
    "lookback_days": 30,
    "recurring_expansion_days": 30,
    "default_retention_mode": "analyze_only",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Define all settings fields for the Calendar plugin."""
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enable Calendar Sync",
            description="Sync calendar events to timeline.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="select",
            label="Sync Interval",
            description="How often to sync calendar events.",
            default="30",
            options=[
                ExtensionFieldOption(label="15 minutes", value="15"),
                ExtensionFieldOption(label="30 minutes", value="30"),
                ExtensionFieldOption(label="1 hour", value="60"),
                ExtensionFieldOption(label="6 hours", value="360"),
            ],
            section="sync",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.lookback_days",
            type="number",
            label="Lookback Days",
            description="How many days of history to sync on initial setup.",
            default=30,
            min=1,
            max=365,
            section="sync",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.recurring_expansion_days",
            type="number",
            label="Recurring Event Expansion",
            description="Days to expand recurring events into the future.",
            default=30,
            min=1,
            max=365,
            section="sync",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How calendar data should be retained.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Full Retention", value="full"),
            ],
            section="retention",
            surface="timeline",
            order=50,
        ),
    ]


class CalendarPlugin(Plugin):
    """Registers the Calendar timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        """Get sensor specifications for Calendar.

        Returns:
            List of sensor tuples (sensor_id, sensor_instance, sensor_spec)
        """
        # Check platform - only supported on Darwin
        if sys.platform != "darwin":
            return []

        # Get settings
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("calendar", {}))

        # Check EventKit availability (but still return sensor spec even if not available)
        reader = None
        try:
            reader = EventKitReader()
            if not reader.is_available():
                reader = None
        except Exception:
            reader = None

        # Create sensor (reader may be None if not available)
        sensor = CalendarTimelineSensor(
            retention_mode=str(settings.get("default_retention_mode", DEFAULT_SETTINGS["default_retention_mode"])),
            reader=reader,
        )

        # Prepare sync mode
        sync_interval_minutes = settings.get("sync_interval_minutes", DEFAULT_SETTINGS["sync_interval_minutes"])

        return [
            (
                "timeline.calendar",
                sensor,
                SensorSpec(
                    sensor_id="timeline.calendar",
                    display_name="Calendar",
                    description="Calendar event ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode="interval",
                    polling_mode="interval",
                    fields=_fields("sensors.calendar"),
                    metadata={
                        "source_type": "calendar",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "sync_interval_minutes": sync_interval_minutes,
                    },
                ),
            )
        ]