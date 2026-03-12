"""Screen Time timeline plugin."""
from __future__ import annotations

import sys
from typing import Any

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .reader import ScreenTimeReader
from .sensor import ScreenTimeTimelineSensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_interval_hours": 1,
    "lookback_days": 30,
    "default_retention_mode": "analyze_only",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Define all settings fields for the Screen Time plugin."""
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enable Screen Time Sync",
            description="Sync screen time data to timeline.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_hours",
            type="select",
            label="Sync Interval",
            description="How often to sync screen time data.",
            default=1,
            options=[
                ExtensionFieldOption(label="Every hour", value=1),
                ExtensionFieldOption(label="Every 6 hours", value=6),
                ExtensionFieldOption(label="Every 12 hours", value=12),
                ExtensionFieldOption(label="Every 24 hours", value=24),
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
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How screen time data should be retained.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Full Retention", value="full"),
            ],
            section="retention",
            surface="timeline",
            order=40,
        ),
    ]


class ScreenTimePlugin(Plugin):
    """Registers the Screen Time timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        """Get sensor specifications for Screen Time.

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
            settings = dict(sensors_settings.get("screen_time", {}))

        # Check if enabled
        if not settings.get("enabled", DEFAULT_SETTINGS["enabled"]):
            return []

        # Check database availability
        try:
            reader = ScreenTimeReader()
            if not reader.is_available():
                return []
        except Exception:
            return []

        # Create sensor
        sensor = ScreenTimeTimelineSensor(
            retention_mode=str(settings.get("default_retention_mode", DEFAULT_SETTINGS["default_retention_mode"])),
            reader=reader,
        )

        # Prepare sync mode
        sync_interval_hours = settings.get("sync_interval_hours", DEFAULT_SETTINGS["sync_interval_hours"])

        return [
            (
                "timeline.screen_time",
                sensor,
                SensorSpec(
                    sensor_id="timeline.screen_time",
                    display_name="Screen Time",
                    description="Screen time data ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode="interval",
                    polling_mode="interval",
                    fields=_fields("sensors.screen_time"),
                    metadata={
                        "source_type": "screen_time",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "sync_interval_hours": sync_interval_hours,
                    },
                ),
            )
        ]
