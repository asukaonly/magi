"""Frontmost app usage timeline plugin."""
from __future__ import annotations

import sys

from magi.events.plugin_ingress import PluginIngressHandlerRegistration
from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .ingress import ScreenTimePluginIngressHandler
from .sensor import ScreenTimeTimelineSensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_interval_minutes": 5,
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Define all settings fields for the frontmost app usage plugin."""
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enable App Usage Sync",
            description="Track frontmost app activation events and write hourly summaries to memory.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="select",
            label="Flush Interval",
            description="How often to flush completed hourly app-usage buckets into memory.",
            default=5,
            options=[
                ExtensionFieldOption(label="Every minute", value="1"),
                ExtensionFieldOption(label="Every 5 minutes", value="5"),
                ExtensionFieldOption(label="Every 15 minutes", value="15"),
                ExtensionFieldOption(label="Every 60 minutes", value="60"),
            ],
            section="sync",
            surface="timeline",
            order=20,
        ),
    ]


class ScreenTimePlugin(Plugin):
    """Registers the frontmost app usage source under the existing package id."""

    def get_plugin_ingress_registrations(self, *, runtime_paths: object) -> list[PluginIngressHandlerRegistration]:
        if sys.platform != "darwin":
            return []

        return [
            PluginIngressHandlerRegistration(
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                handler=ScreenTimePluginIngressHandler(runtime_paths=runtime_paths),
            )
        ]

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        if sys.platform != "darwin":
            return []

        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("screen_time", {}))

        sensor = ScreenTimeTimelineSensor()
        sync_interval_minutes = int(settings.get("sync_interval_minutes", DEFAULT_SETTINGS["sync_interval_minutes"]))

        return [
            (
                "timeline.screen_time",
                sensor,
                SensorSpec(
                    sensor_id="timeline.screen_time",
                    display_name="App Usage",
                    description="Event-driven frontmost app usage aggregated into hourly summaries.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode="interval",
                    polling_mode="interval",
                    fields=_fields("sensors.screen_time"),
                    metadata={
                        "source_type": "screen_time",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "sync_interval_minutes": sync_interval_minutes,
                    },
                ),
            )
        ]
