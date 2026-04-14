"""Cross-platform system media playback timeline plugin."""
from __future__ import annotations

import sys

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .sensor import SystemMediaTimelineSensor
from .state import MediaSessionStateStore

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_interval_minutes": 1,
    "min_session_seconds": 30,
    "pause_timeout_seconds": 300,
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Settings fields for the system media plugin."""
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enable System Media Sync",
            description="Track media playback from any player via OS transport controls.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="select",
            label="Sync Interval",
            description="How often completed listening sessions are flushed into memory.",
            default=1,
            options=[
                ExtensionFieldOption(label="Every 1 minute", value="1"),
                ExtensionFieldOption(label="Every 5 minutes", value="5"),
                ExtensionFieldOption(label="Every 15 minutes", value="15"),
            ],
            section="sync",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.min_session_seconds",
            type="number",
            label="Minimum Session Duration (seconds)",
            description="Listening sessions shorter than this are discarded as noise.",
            default=30,
            min=5,
            section="sync",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.pause_timeout_seconds",
            type="number",
            label="Pause Timeout (seconds)",
            description="A pause longer than this closes the current listening session.",
            default=300,
            min=30,
            section="sync",
            surface="timeline",
            order=40,
        ),
    ]


class SystemMediaPlugin(Plugin):
    """Registers the system-media timeline sensor."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        if sys.platform not in ("win32", "darwin"):
            return []

        settings: dict = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("system_media", {}))

        min_session_s = int(settings.get("min_session_seconds", DEFAULT_SETTINGS["min_session_seconds"]))
        pause_timeout_s = int(settings.get("pause_timeout_seconds", DEFAULT_SETTINGS["pause_timeout_seconds"]))
        sync_interval = int(settings.get("sync_interval_minutes", DEFAULT_SETTINGS["sync_interval_minutes"]))

        state_store = MediaSessionStateStore(
            pause_timeout_s=pause_timeout_s,
            min_session_s=min_session_s,
        )
        sensor = SystemMediaTimelineSensor(state_store=state_store)

        return [
            (
                "timeline.system_media",
                sensor,
                SensorSpec(
                    sensor_id="timeline.system_media",
                    display_name="System Media",
                    description="Cross-platform media playback tracking via OS transport controls.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode="interval",
                    polling_mode="interval",
                    fields=_fields("sensors.system_media"),
                    metadata={
                        "source_type": "system_media",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "sync_interval_minutes": sync_interval,
                    },
                ),
            )
        ]
