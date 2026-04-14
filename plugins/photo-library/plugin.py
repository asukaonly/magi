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
    "source_paths": [],
    "exclude_patterns": ["**/thumbnails", "**/.cache", "**/Thumbs.db", "**/@eaDir"],
    "max_items_per_sync": 200,
    "analysis_features": ["exif"],
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
            key=f"{prefix}.source_paths",
            type="path",
            label="Photo Directories",
            description="Local directories containing photos to scan. Add one or more paths.",
            default=[],
            required=True,
            section="general",
            surface="timeline",
            order=15,
            placeholder="/path/to/photos",
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.exclude_patterns",
            type="tags",
            label="Exclude Patterns",
            description="Glob patterns for directories or files to skip (e.g. thumbnails, .cache).",
            default=["**/thumbnails", "**/.cache", "**/Thumbs.db", "**/@eaDir"],
            section="general",
            surface="timeline",
            order=16,
            placeholder="**/thumbnails",
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
            key=f"{prefix}.analysis_features",
            type="tags",
            label="Analysis Features",
            description="Metadata extraction capabilities to apply.",
            default=["exif"],
            options=[
                ExtensionFieldOption(label="EXIF Metadata", value="exif"),
                ExtensionFieldOption(label="GPS Geocoding", value="geocode"),
            ],
            section="general",
            surface="timeline",
            order=45,
        ),
    ]


class PhotoLibraryPlugin(Plugin):
    """Registers the photo library timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        settings: dict[str, Any] = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("photo_library", {}))

        # Support both legacy source_path (string) and new source_paths (list)
        source_paths: list[str] = []
        raw_paths = settings.get("source_paths")
        if isinstance(raw_paths, list):
            source_paths = [str(p) for p in raw_paths if p]
        elif not raw_paths:
            legacy = settings.get("source_path")
            if legacy:
                source_paths = [str(legacy)]

        # Resolve exclude patterns
        raw_excludes = settings.get("exclude_patterns")
        exclude_patterns: list[str] = []
        if isinstance(raw_excludes, list):
            exclude_patterns = [str(p) for p in raw_excludes if p]

        sensor = PhotoLibraryTimelineSensor(
            source_paths=source_paths,
            max_items_per_sync=int(settings.get("max_items_per_sync", DEFAULT_SETTINGS["max_items_per_sync"])),
            analysis_features=list(settings.get("analysis_features", DEFAULT_SETTINGS["analysis_features"])),
            exclude_patterns=exclude_patterns,
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
