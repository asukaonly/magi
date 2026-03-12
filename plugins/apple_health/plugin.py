"""Apple Health timeline plugin."""
from __future__ import annotations

import sys
from typing import Any, Dict, List

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec
from plugins.apple_health.reader import HealthKitReader
from plugins.apple_health.sensor import AppleHealthTimelineSensor
from plugins.apple_health.types import HEALTH_DATA_TYPES, get_default_enabled_types, get_enabled_types

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_mode": "manual",
    "sync_interval_hours": 1,
    "lookback_days": 7,
    "types": {
        "steps": True,
        "sleep": True,
        "heart_rate": False,
        "distance": False,
        "flights": False,
        "active_energy": False,
        "workout": False,
    },
    "default_retention_mode": "analyze_only",
    "storage_mode": "managed",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Define all settings fields for the Apple Health plugin."""
    fields = []

    # Data type toggles
    type_order = 10
    for type_key, data_type in HEALTH_DATA_TYPES.items():
        fields.append(
            ExtensionFieldSpec(
                key=f"{prefix}.types.{type_key}",
                type="switch",
                label=data_type.display_name,
                description=data_type.description,
                default=DEFAULT_SETTINGS["types"][type_key],
                section="data_types",
                surface="timeline",
                order=type_order,
            )
        )
        type_order += 5

    # Sync settings
    fields.extend([
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_hours",
            type="number",
            label="Sync Interval (hours)",
            description="How often to sync data (hours).",
            default=1,
            min=1,
            section="sync",
            surface="timeline",
            order=50,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.lookback_days",
            type="number",
            label="Lookback Days",
            description="How many days of history to sync on initial setup.",
            default=7,
            min=1,
            max=365,
            section="sync",
            surface="timeline",
            order=60,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How health data should be retained.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Full Retention", value="full"),
            ],
            section="retention",
            surface="timeline",
            order=70,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.storage_mode",
            type="select",
            label="Storage Mode",
            description="Where to store ingested health data.",
            default="managed",
            options=[
                ExtensionFieldOption(label="Managed", value="managed"),
                ExtensionFieldOption(label="Local", value="local"),
            ],
            section="storage",
            surface="timeline",
            order=80,
        ),
    ])

    return fields


def _get_enabled_types_from_settings(settings: dict) -> list[str]:
    """Get enabled types from settings.

    Args:
        settings: Plugin settings dictionary

    Returns:
        List of enabled type keys
    """
    # Get apple_health settings
    apple_health_settings = settings.get("sensors", {}).get("apple_health", {})

    if not apple_health_settings or "types" not in apple_health_settings:
        # Return types that are True in DEFAULT_SETTINGS["types"]
        return [k for k, v in DEFAULT_SETTINGS["types"].items() if v]

    enabled_types = []
    types_config = apple_health_settings.get("types", {})

    if isinstance(types_config, dict):
        for type_key, enabled in types_config.items():
            if enabled and type_key in HEALTH_DATA_TYPES:
                enabled_types.append(type_key)

    return enabled_types


class AppleHealthPlugin(Plugin):
    """Registers the Apple Health timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        """Get sensor specifications for Apple Health.

        Returns:
            List of sensor tuples (sensor_id, sensor_instance, sensor_spec)
        """
        # Check platform - only supported on Darwin
        if sys.platform != "darwin":
            return []

        # Check HealthKit availability
        try:
            reader = HealthKitReader()
            if not reader.is_available():
                return []
        except Exception:
            return []

        # Get settings
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("apple_health", {}))

        print(f"Settings for apple_health: {settings}")

        # Get enabled types from settings
        enabled_types = _get_enabled_types_from_settings(settings)
        print(f"Enabled types: {enabled_types}")
        if not enabled_types:
            return []

        # Get health data type objects
        enabled_health_types = [
            HEALTH_DATA_TYPES[type_key] for type_key in enabled_types
            if type_key in HEALTH_DATA_TYPES
        ]
        print(f"Enabled health types count: {len(enabled_health_types)}")

        if not enabled_health_types:
            return []

        # Create sensor
        sensor = AppleHealthTimelineSensor(
            retention_mode=str(settings.get("default_retention_mode", DEFAULT_SETTINGS["default_retention_mode"])),
            enabled_types=enabled_health_types,
            reader=reader,
        )

        # Prepare sync mode
        sync_mode = str(settings.get("sync_mode", DEFAULT_SETTINGS["sync_mode"]))
        if sync_mode == "manual":
            sync_mode = "interval"

        result = [
            (
                "timeline.apple_health",
                sensor,
                SensorSpec(
                    sensor_id="timeline.apple_health",
                    display_name="Apple Health",
                    description="Apple Health data ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode=sync_mode,
                    polling_mode="interval",
                    fields=_fields("sensors.apple_health"),
                    metadata={
                        "source_type": "apple_health",
                        "default_settings": dict(DEFAULT_SETTINGS),
                    },
                ),
            )
        ]

        print(f"Returning sensors: {len(result)}")
        return result