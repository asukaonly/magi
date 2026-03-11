"""Timeline sensor for local photo libraries."""
from __future__ import annotations

from pathlib import Path

from ..contracts import TimelineContentBlock, TimelineEvent
from .base import TimelineSensorBase


class PhotoLibraryTimelineSensor(TimelineSensorBase):
    sensor_id = "timeline.photo_library"
    display_name = "Photo Library"
    source_type = "photo_library"
    polling_mode = "interval"
    default_interval = 60
    update_key_fields = ("asset_local_id", "modified_at", "analysis_scope", "file_hash")
    relation_edge_whitelist = ("CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED")

    @property
    def default_retention_mode(self) -> str:
        return "retain_raw"

    def source_item_identity(self, item: dict[str, object]) -> str:
        return str(item.get("asset_local_id", "photo"))

    def source_item_version_fingerprint(self, item: dict[str, object]) -> str:
        return "|".join(
            [
                str(item.get("modified_at", "")),
                str(item.get("analysis_scope", "")),
                str(item.get("file_hash", "")),
            ]
        )

    async def fetch_item(self, item: dict[str, object]) -> dict[str, object]:
        path = Path(str(item.get("path", ""))).resolve()
        if self.source_path is None:
            raise ValueError("Photo library source_path is required")

        allowed_root = Path(self.source_path).resolve()
        if allowed_root not in {path, *path.parents}:
            raise ValueError(f"Photo path {path} is outside configured library scope {allowed_root}")
        return dict(item)

    async def build_timeline_event(self, item: dict[str, object]) -> TimelineEvent:
        path = str(item.get("path", ""))
        return self._build_event(
            source_item_id=self.source_item_identity(item),
            title=Path(path).name or "Photo",
            summary=Path(path).name or "Captured photo",
            occurred_at=float(item.get("modified_at") or 0.0),
            raw_payload_ref=path,
            content_blocks=[TimelineContentBlock(kind="image", value=path)],
            tags=["photo_library"],
        )

    async def extract_candidates(self, item: dict[str, object]) -> dict[str, object]:
        return {
            "entities": list(item.get("entities", [])),
            "tags": ["photo_library"],
            "relation_candidates": list(item.get("relation_candidates", [])),
        }
