"""Official timeline sensor plugin."""
from __future__ import annotations

from copy import deepcopy

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec
from magi.timeline.sensors import (
    BrowserHistoryTimelineSensor,
    ChatTimelineSensor,
    ManualJournalTimelineSensor,
    PhotoLibraryTimelineSensor,
)


def _base_fields(prefix: str, *, include_path: bool = False, include_fetch_toggle: bool = False) -> list[ExtensionFieldSpec]:
    fields = [
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
            default=15,
            section="general",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How raw content should be handled.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Retain Raw", value="retain_raw"),
            ],
            section="storage",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.storage_mode",
            type="select",
            label="Storage Mode",
            description="Whether assets are managed or referenced externally.",
            default="managed",
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
            default=[],
            section="analysis",
            surface="timeline",
            order=60,
        ),
    ]
    if include_path:
        fields.append(
            ExtensionFieldSpec(
                key=f"{prefix}.source_path",
                type="path",
                label="Source Path",
                description="Optional local path or root directory for this source.",
                default="",
                section="storage",
                surface="timeline",
                order=45,
            )
        )
    if include_fetch_toggle:
        fields.append(
            ExtensionFieldSpec(
                key=f"{prefix}.fetch_page_content",
                type="switch",
                label="Fetch Page Content",
                description="Whether to include captured page content.",
                default=False,
                section="analysis",
                surface="timeline",
                order=55,
            )
        )
    return fields


DEFAULT_SOURCE_SETTINGS = {
    "chat": {
        "enabled": True,
        "sync_mode": "watch",
        "sync_interval_minutes": 1,
        "default_retention_mode": "analyze_only",
        "storage_mode": "managed",
        "edge_whitelist": ["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "INTERACTED_WITH"],
    },
    "manual_journal": {
        "enabled": True,
        "sync_mode": "manual",
        "sync_interval_minutes": 1,
        "default_retention_mode": "retain_raw",
        "storage_mode": "managed",
        "edge_whitelist": ["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "CREATED", "RELATED_TO"],
    },
    "browser_history": {
        "enabled": True,
        "sync_mode": "interval",
        "sync_interval_minutes": 30,
        "default_retention_mode": "analyze_only",
        "storage_mode": "managed",
        "source_path": "",
        "fetch_page_content": False,
        "edge_whitelist": ["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
    },
    "photo_library": {
        "enabled": True,
        "sync_mode": "interval",
        "sync_interval_minutes": 60,
        "default_retention_mode": "retain_raw",
        "storage_mode": "external_reference",
        "source_path": "",
        "edge_whitelist": ["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
    },
}


class CoreTimelinePlugin(Plugin):
    """Registers official timeline sensors."""

    def _source_settings(self, source_type: str) -> dict:
        current = deepcopy(DEFAULT_SOURCE_SETTINGS[source_type])
        current.update(
            dict(
                self.settings.get("sensors", {}).get(source_type, {})
                if isinstance(self.settings.get("sensors", {}), dict)
                else {}
            )
        )
        return current

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        specs = []
        source_map = {
            "chat": (
                ChatTimelineSensor,
                _base_fields("sensors.chat"),
                "Chat",
                "Chat turns promoted into the user timeline.",
            ),
            "manual_journal": (
                ManualJournalTimelineSensor,
                _base_fields("sensors.manual_journal"),
                "Manual Journal",
                "User-authored journal entries and attachments.",
            ),
            "browser_history": (
                BrowserHistoryTimelineSensor,
                _base_fields("sensors.browser_history", include_path=True, include_fetch_toggle=True),
                "Browser History",
                "Visited URLs and optional page content snapshots.",
            ),
            "photo_library": (
                PhotoLibraryTimelineSensor,
                _base_fields("sensors.photo_library", include_path=True),
                "Photo Library",
                "Photo assets referenced from a local library path.",
            ),
        }

        for source_type, (sensor_class, fields, display_name, description) in source_map.items():
            settings = self._source_settings(source_type)
            sensor = sensor_class(
                retention_mode=settings.get("default_retention_mode"),
                source_path=settings.get("source_path") or None,
                fetch_page_content=bool(settings.get("fetch_page_content", False)),
            )
            specs.append(
                (
                    f"timeline.{source_type}",
                    sensor,
                    SensorSpec(
                        sensor_id=f"timeline.{source_type}",
                        display_name=display_name,
                        description=description,
                        domain="timeline",
                        surface="timeline",
                        sync_mode=str(settings.get("sync_mode", "manual")),
                        polling_mode=getattr(sensor, "polling_mode", "manual"),
                        fields=fields,
                        metadata={
                            "source_type": source_type,
                            "default_settings": deepcopy(DEFAULT_SOURCE_SETTINGS[source_type]),
                        },
                    ),
                )
            )
        return specs
