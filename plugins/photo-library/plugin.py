"""Photo library timeline plugin."""
from __future__ import annotations

from collections import Counter
from typing import Any

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec
from .sensor import PhotoLibraryTimelineSensor


DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "sync_mode": "manual",
    "sync_interval_minutes": 60,
    "default_retention_mode": "retain_raw",
    "source_path": "",
    "max_items_per_sync": 200,
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enable",
            description="Whether photo library sync is active.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.source_path",
            type="path",
            label="Photo Directory",
            description="Local directory containing photos to scan.",
            default="",
            required=True,
            section="general",
            surface="timeline",
            order=15,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_mode",
            type="select",
            label="Sync Mode",
            description="How photo library should be synchronized.",
            default="manual",
            options=[
                ExtensionFieldOption(label="Manual", value="manual"),
                ExtensionFieldOption(label="Interval", value="interval"),
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
            default=60,
            section="general",
            surface="timeline",
            order=30,
            depends_on_key=f"{prefix}.sync_mode",
            depends_on_values=["interval"],
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.max_items_per_sync",
            type="number",
            label="Max Items Per Sync",
            description="Maximum number of photos to process per sync run.",
            default=200,
            section="general",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How raw photo data should be handled.",
            default="retain_raw",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Retain Raw", value="retain_raw"),
            ],
            section="storage",
            surface="timeline",
            order=50,
        ),
    ]


class PhotoLibraryPlugin(Plugin):
    """Registers the photo library timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        settings: dict[str, Any] = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("photo_library", {}))
        sensor = PhotoLibraryTimelineSensor(
            retention_mode=str(settings.get("default_retention_mode") or DEFAULT_SETTINGS["default_retention_mode"]),
            source_path=(str(settings.get("source_path")) if settings.get("source_path") else None),
            max_items_per_sync=int(settings.get("max_items_per_sync", DEFAULT_SETTINGS["max_items_per_sync"])),
        )
        return [
            (
                "timeline.photo_library",
                sensor,
                SensorSpec(
                    sensor_id="timeline.photo_library",
                    display_name="Photo Library",
                    description="Scan a local photo directory, extract EXIF metadata, and ingest into the timeline.",
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

    def build_temporal_summary_features(
        self,
        *,
        source_type: str,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> dict[str, object] | None:
        """Build photo-specific temporal summary features."""
        _ = summary_category, period_start, period_end
        if source_type != "photo_library":
            return None

        camera_counter: Counter[str] = Counter()
        gps_count = 0
        screenshot_count = 0
        timestamps: list[float] = []
        extensions: Counter[str] = Counter()

        for event in events:
            metadata = event.get("metadata_json")
            if not isinstance(metadata, dict):
                continue
            timeline = metadata.get("timeline")
            if not isinstance(timeline, dict):
                continue
            provenance = timeline.get("provenance")
            if not isinstance(provenance, dict):
                continue
            camera = str(provenance.get("camera") or "").strip()
            if camera:
                camera_counter[camera] += 1
            if provenance.get("latitude") is not None:
                gps_count += 1
            if str(provenance.get("image_type", "")) == "screenshot":
                screenshot_count += 1
            filename = str(provenance.get("filename") or "")
            if "." in filename:
                extensions[filename.rsplit(".", 1)[-1].lower()] += 1
            if event.get("timestamp") is not None:
                timestamps.append(float(event["timestamp"]))

        if not events:
            return None

        top_cameras = [
            {"camera": cam, "count": cnt}
            for cam, cnt in camera_counter.most_common(3)
        ]

        summary_lines: list[str] = []
        if top_cameras:
            joined = " and ".join(c["camera"] for c in top_cameras[:2])
            summary_lines.append(f"Photos taken with {joined}.")
        if gps_count > 0:
            summary_lines.append(f"{gps_count} photos have GPS coordinates.")
        if screenshot_count > 0:
            photo_count = len(events) - screenshot_count
            summary_lines.append(f"{photo_count} photos, {screenshot_count} screenshots.")

        return {
            "feature_type": "photo_library",
            "event_count": len(events),
            "cameras": top_cameras,
            "gps_count": gps_count,
            "screenshot_count": screenshot_count,
            "format_distribution": dict(extensions.most_common(5)),
            "summary_lines": summary_lines,
        }
