"""Calendar timeline plugin."""
from __future__ import annotations

import sys
from typing import Any

from magi.plugins import ActivationFlowSpec, ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .reader import EventKitReader
from .sensor import CalendarTimelineSensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "authorization_configured": False,
    "sync_mode": "interval",
    "sync_interval_minutes": 30,
    "lookback_days": 30,
    "recurring_expansion_days": 30,
    "default_retention_mode": "full",
}


def _activation_flow(prefix: str) -> ActivationFlowSpec:
    """Define first-enable authorization flow for Calendar."""
    return ActivationFlowSpec(
        title="Connect Calendar",
        description="Allow Magi to read your calendar events for timeline sync.",
        confirm_label="Allow calendar access",
        cancel_label="Not now",
        authorize_on_confirm=True,
        enabled_key=f"{prefix}.enabled",
        configured_key=f"{prefix}.authorization_configured",
        fields=[],
    )


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
            key=f"{prefix}.sync_mode",
            type="select",
            label="Sync Mode",
            description="Choose whether calendar sync runs manually or on a schedule.",
            default="interval",
            options=[
                ExtensionFieldOption(label="Manual", value="manual"),
                ExtensionFieldOption(label="Scheduled", value="interval"),
            ],
            section="sync",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="select",
            label="Sync Interval",
            description="How often to sync calendar events when scheduled sync is enabled.",
            default="30",
            options=[
                ExtensionFieldOption(label="15 minutes", value="15"),
                ExtensionFieldOption(label="30 minutes", value="30"),
                ExtensionFieldOption(label="1 hour", value="60"),
                ExtensionFieldOption(label="6 hours", value="360"),
            ],
            section="sync",
            surface="timeline",
            order=30,
            depends_on_key=f"{prefix}.sync_mode",
            depends_on_values=["interval"],
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
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.recurring_expansion_days",
            type="number",
            label="Future Recurring Event Window",
            description="How many future days of recurring events should be prefetched into the timeline.",
            default=30,
            min=1,
            max=365,
            section="sync",
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

        source_enabled = bool(settings.get("enabled", DEFAULT_SETTINGS["enabled"]))

        # Check EventKit availability (but still return sensor spec even if not available)
        reader = None
        if source_enabled:
            try:
                reader = EventKitReader()
                if not reader.is_available():
                    reader = None
            except Exception:
                reader = None

        # Create sensor (reader may be None if not available)
        sensor = CalendarTimelineSensor(
            retention_mode=DEFAULT_SETTINGS["default_retention_mode"],
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
                        "activation_flow": _activation_flow("sensors.calendar").model_dump(),
                    },
                ),
            )
        ]
