"""Photo library timeline plugin."""
from __future__ import annotations

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec
from magi.timeline.sensors import PhotoLibraryTimelineSensor


DEFAULT_SETTINGS = {
    "enabled": True,
    "sync_mode": "interval",
    "sync_interval_minutes": 60,
    "default_retention_mode": "retain_raw",
    "storage_mode": "external_reference",
    "source_path": "",
    "edge_whitelist": ["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enabled",
            description="Whether this source is active.",
            default=True,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_mode",
            type="select",
            label="Sync Mode",
            description="How this source should be triggered.",
            default="interval",
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
            description="Polling interval for interval-based sources.",
            default=60,
            section="general",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How raw content should be handled.",
            default="retain_raw",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Retain Raw", value="retain_raw"),
            ],
            section="storage",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.source_path",
            type="path",
            label="Source Path",
            description="Optional local path or root directory for this source.",
            default="",
            section="storage",
            surface="timeline",
            order=45,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.storage_mode",
            type="select",
            label="Storage Mode",
            description="Whether assets are managed or referenced externally.",
            default="external_reference",
            options=[
                ExtensionFieldOption(label="Managed", value="managed"),
                ExtensionFieldOption(label="External Reference", value="external_reference"),
            ],
            section="storage",
            surface="timeline",
            order=50,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.edge_whitelist",
            type="tags",
            label="Edge Whitelist",
            description="Relationship edge types this source may write into the user graph.",
            default=["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
            section="analysis",
            surface="timeline",
            order=60,
        ),
    ]


class PhotoLibraryPlugin(Plugin):
    """Registers the photo library timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("photo_library", {}))
        sensor = PhotoLibraryTimelineSensor(
            retention_mode=str(settings.get("default_retention_mode") or DEFAULT_SETTINGS["default_retention_mode"]),
            source_path=(str(settings.get("source_path")) if settings.get("source_path") else None),
        )
        return [
            (
                "timeline.photo_library",
                sensor,
                SensorSpec(
                    sensor_id="timeline.photo_library",
                    display_name="Photo Library",
                    description="Photo assets referenced from a local library path.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode=str(settings.get("sync_mode", DEFAULT_SETTINGS["sync_mode"])),
                    polling_mode=getattr(sensor, "polling_mode", "interval"),
                    fields=_fields("sensors.photo_library"),
                    metadata={
                        "source_type": "photo_library",
                        "default_settings": dict(DEFAULT_SETTINGS),
                    },
                ),
            )
        ]
