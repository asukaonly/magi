"""Timeline sensor for local photo libraries."""
from __future__ import annotations

from pathlib import Path

from ...awareness.sensor_base import SensorBase
from ...awareness.sensor_output import ContentBlock, SensorMemoryPolicy, SensorOutput, SensorOutputMetadata


class PhotoLibraryTimelineSensor(SensorBase):
    sensor_id = "timeline.photo_library"
    display_name = "Photo Library"
    source_type = "photo_library"
    polling_mode = "interval"
    default_interval = 60
    update_key_fields = ("asset_local_id", "modified_at", "analysis_scope", "file_hash")
    relation_edge_whitelist = ("CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED")

    memory_policy = SensorMemoryPolicy(
        retention_class="compressible",
        cognition_eligible=True,
        importance_bias=0.6,
    )

    def __init__(
        self,
        *,
        retention_mode: str | None = None,
        source_path: str | None = None,
        **_kw: object,
    ) -> None:
        super().__init__()
        self.retention_mode = retention_mode or "retain_raw"
        self.source_path = source_path

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

    async def build_output(self, item: dict[str, object]) -> SensorOutput:
        path = str(item.get("path", ""))
        return self._build_output(
            source_item_id=self.source_item_identity(item),
            title=Path(path).name or "Photo",
            summary=Path(path).name or "Captured photo",
            occurred_at=float(item.get("modified_at") or 0.0),
            raw_payload_ref=path,
            content_blocks=[ContentBlock(kind="image", value=path)],
            tags=["photo_library"],
            domain_payload={"retention_mode": self.retention_mode},
        )

    async def extract_metadata(self, item: dict[str, object]) -> SensorOutputMetadata:
        return SensorOutputMetadata(
            entities=list(item.get("entities", [])),
            tags=["photo_library"],
            relation_candidates=list(item.get("relation_candidates", [])),
        )
