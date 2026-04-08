"""NetEase Cloud Music timeline plugin."""
from __future__ import annotations

import sys

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec
from .reader import DEFAULT_DB_PATH
from .sensor import NeteaseMusicTimelineSensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_mode": "manual",
    "sync_interval_minutes": 30,
    "min_play_duration": 20,
    "db_path": DEFAULT_DB_PATH,
    "default_retention_mode": "analyze_only",
    "storage_mode": "managed",
    "initial_sync_policy": "from_now",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enabled",
            description="Whether NetEase Music sync is active.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_mode",
            type="select",
            label="Sync Mode",
            description="How NetEase Music history should be synchronized.",
            default="manual",
            options=[
                ExtensionFieldOption(label="Manual", value="manual"),
                ExtensionFieldOption(label="Interval", value="interval"),
                ExtensionFieldOption(label="Watch", value="watch"),
            ],
            section="general",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="number",
            label="Sync Interval (minutes)",
            description="Polling interval used for interval-based sync.",
            default=30,
            section="general",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.min_play_duration",
            type="number",
            label="Minimum Play Duration (seconds)",
            description="Minimum track play duration to include in timeline (seconds).",
            default=20,
            min=1,
            section="general",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.db_path",
            type="path",
            label="Database Path",
            description="Path to NetEase Cloud Music local.db file.",
            default=DEFAULT_DB_PATH,
            section="general",
            surface="timeline",
            order=50,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How track history should be retained.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Full Retention", value="full"),
            ],
            section="analysis",
            surface="timeline",
            order=60,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.storage_mode",
            type="select",
            label="Storage Mode",
            description="Where to store ingested track data.",
            default="managed",
            options=[
                ExtensionFieldOption(label="Managed", value="managed"),
                ExtensionFieldOption(label="Local", value="local"),
            ],
            section="analysis",
            surface="timeline",
            order=70,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.initial_sync_policy",
            type="select",
            label="Initial Sync Policy",
            description="How the first sync should seed the timeline before running.",
            default="from_now",
            options=[
                ExtensionFieldOption(label="Backfill all history", value="full"),
                ExtensionFieldOption(label="Sync recent days", value="lookback_days"),
                ExtensionFieldOption(label="Only new records from now on", value="from_now"),
            ],
            section="activation",
            surface="timeline",
            order=80,
        ),
    ]


class NeteaseMusicPlugin(Plugin):
    """Registers the NetEase Music timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        if sys.platform != "darwin":
            return []

        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("netease_music", {}))

        sensor = NeteaseMusicTimelineSensor(
            min_play_duration=int(settings.get("min_play_duration") or DEFAULT_SETTINGS["min_play_duration"]),
            source_path=str(settings.get("db_path") or DEFAULT_SETTINGS["db_path"]),
            retention_mode=str(settings.get("default_retention_mode") or DEFAULT_SETTINGS["default_retention_mode"]),
        )

        return [
            (
                "timeline.netease_music",
                sensor,
                SensorSpec(
                    sensor_id="timeline.netease_music",
                    display_name="NetEase Cloud Music",
                    description="Local NetEase Cloud Music play history ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode=str(settings.get("sync_mode", DEFAULT_SETTINGS["sync_mode"])),
                    polling_mode=getattr(sensor, "polling_mode", "interval"),
                    fields=_fields("sensors.netease_music"),
                    metadata={
                        "source_type": "netease_music",
                        "default_settings": dict(DEFAULT_SETTINGS),
                    },
                ),
            )
        ]