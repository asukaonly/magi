"""Timeline sensor for local photo libraries."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from magi.awareness import (
    ContentBlock,
    L2BatchPolicy,
    SensorBase,
    SensorMemoryPolicy,
    SensorOutput,
    SensorOutputMetadata,
    SensorSyncContext,
    SensorSyncResult,
)

from .normalizers import (
    build_entity_hints,
    build_relation_candidates,
    camera_display_name,
    image_dimensions_label,
    shooting_params_summary,
)
from .reader import PhotoLibraryReader


class PhotoLibraryTimelineSensor(SensorBase):
    """Pull-sync sensor that scans a local directory for photos and extracts EXIF metadata."""

    sensor_id = "timeline.photo_library"
    display_name = "Photo Library"
    source_type = "photo_library"
    polling_mode = "interval"
    default_interval = 60
    update_key_fields = ("asset_local_id", "file_hash")
    relation_edge_whitelist = ("CAPTURED", "RELATED_TO", "CREATED")
    supports_pull_sync = True

    memory_policy = SensorMemoryPolicy(
        retention_class="compressible",
        cognition_eligible=True,
        importance_bias=0.6,
    )

    _l2_batch_shard_count = 4

    def __init__(
        self,
        *,
        retention_mode: str | None = None,
        source_path: str | None = None,
        max_items_per_sync: int = 200,
        reader: PhotoLibraryReader | None = None,
    ) -> None:
        super().__init__()
        self.retention_mode = retention_mode or "retain_raw"
        self.source_path = source_path
        self.max_items_per_sync = max_items_per_sync
        self._reader = reader or PhotoLibraryReader()

    # ------------------------------------------------------------------
    # Identity & dedup
    # ------------------------------------------------------------------

    def source_item_identity(self, item: dict[str, Any]) -> str:
        return str(item.get("asset_local_id") or item.get("file_hash") or "photo")

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        parts = [
            str(item.get("file_hash", "")),
            str(item.get("modified_at", "")),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # L2 batching
    # ------------------------------------------------------------------

    def l2_batch_policy(self, output: SensorOutput) -> L2BatchPolicy | None:
        camera = str(output.provenance.get("camera", "")).strip()
        parts = [self.source_type]
        if camera:
            parts.append(camera)
        catch_up_owner = None
        if camera:
            digest = hashlib.sha1(camera.lower().encode("utf-8")).hexdigest()
            shard = int(digest[:8], 16) % self._l2_batch_shard_count
            catch_up_owner = f"{self.source_type}:catchup:{shard}"
        return L2BatchPolicy(
            owner=":".join(parts),
            catch_up_owner=catch_up_owner,
            max_events=15,
            min_ready_events=5,
            max_wait_seconds=300,
        )

    # ------------------------------------------------------------------
    # Pull-sync
    # ------------------------------------------------------------------

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )
        source_path = str(
            sensor_settings.get("source_path") or self.source_path or ""
        )
        if not source_path:
            return SensorSyncResult(
                items=[],
                stats={"count": 0, "error": "source_path not configured"},
            )

        # Use cursor as minimum modified-at watermark for incremental sync
        min_modified_at = 0.0
        if context.last_cursor:
            try:
                min_modified_at = float(context.last_cursor)
            except (ValueError, TypeError):
                pass

        limit = min(max(1, context.limit), self.max_items_per_sync)
        result = self._reader.scan_directory(
            source_path,
            limit=limit,
            min_modified_at=min_modified_at,
        )

        # Validate all paths are within configured scope
        allowed_root = Path(source_path).expanduser().resolve()
        safe_items: list[dict[str, Any]] = []
        for item in result.items:
            item_path = Path(str(item.get("path", ""))).resolve()
            if allowed_root in {item_path, *item_path.parents}:
                safe_items.append(item)

        # Advance cursor to the max modified_at seen
        next_cursor = context.last_cursor
        watermark_ts = context.last_success_at
        if safe_items:
            max_mtime = max(float(it.get("modified_at") or 0.0) for it in safe_items)
            next_cursor = str(max_mtime)
            watermark_ts = max_mtime

        return SensorSyncResult(
            items=safe_items,
            next_cursor=next_cursor,
            watermark_ts=watermark_ts,
            stats={
                "count": len(safe_items),
                "total_scanned": result.total_scanned,
                "errors": result.errors,
            },
        )

    # ------------------------------------------------------------------
    # Output building
    # ------------------------------------------------------------------

    async def fetch_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Validate path scope. Items are already enriched by the reader."""
        path = Path(str(item.get("path", ""))).resolve()
        if not self.source_path:
            raise ValueError("Photo library source_path is required")
        allowed_root = Path(self.source_path).expanduser().resolve()
        if allowed_root not in {path, *path.parents}:
            raise ValueError(
                f"Photo path {path} is outside configured library scope {allowed_root}"
            )
        return dict(item)

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        path = str(item.get("path", ""))
        filename = str(item.get("filename") or Path(path).name or "Photo")
        camera = camera_display_name(
            str(item.get("camera_make", "")),
            str(item.get("camera_model", "")),
        )
        params = shooting_params_summary(item)
        dimensions = image_dimensions_label(
            int(item.get("image_width") or 0),
            int(item.get("image_height") or 0),
        )

        # Build i18n summary
        image_type = str(item.get("image_type", "photo"))
        if image_type == "screenshot":
            device = camera or str(item.get("camera_model", ""))
            if device:
                summary = self.t("summary.screenshot_with_device", filename=filename, device=device)
            else:
                summary = self.t("summary.screenshot", filename=filename)
        elif camera and params:
            summary = self.t("summary.with_camera_params", filename=filename, camera=camera, params=params)
        elif camera:
            summary = self.t("summary.with_camera", filename=filename, camera=camera)
        else:
            summary = self.t("summary.basic", filename=filename)

        content_blocks = [ContentBlock(kind="image", value=path)]
        if camera:
            content_blocks.append(ContentBlock(kind="text", value=camera))
        if params:
            content_blocks.append(ContentBlock(kind="text", value=params))
        if dimensions:
            content_blocks.append(ContentBlock(kind="text", value=dimensions))

        lat = item.get("latitude")
        lon = item.get("longitude")
        if lat is not None and lon is not None:
            content_blocks.append(ContentBlock(kind="text", value=f"GPS: {lat:.6f}, {lon:.6f}"))

        occurred_at = float(item.get("capture_timestamp") or item.get("modified_at") or 0.0)

        return self._build_output(
            source_item_id=self.source_item_identity(item),
            title=filename,
            summary=summary,
            occurred_at=occurred_at,
            raw_payload_ref=path,
            content_blocks=content_blocks,
            tags=[t for t in ("photo_library", image_type, item.get("extension", "")) if t],
            provenance={
                "sensor_id": self.sensor_id,
                "camera": camera,
                "camera_make": str(item.get("camera_make", "")),
                "camera_model": str(item.get("camera_model", "")),
                "lens_model": str(item.get("lens_model", "")),
                "focal_length": str(item.get("focal_length", "")),
                "aperture": str(item.get("aperture", "")),
                "exposure_time": str(item.get("exposure_time", "")),
                "iso": str(item.get("iso", "")),
                "image_width": int(item.get("image_width") or 0),
                "image_height": int(item.get("image_height") or 0),
                "latitude": lat,
                "longitude": lon,
                "file_hash": str(item.get("file_hash", "")),
                "filename": filename,
                "image_type": image_type,
            },
            domain_payload={"retention_mode": self.retention_mode},
        )

    async def extract_metadata(self, item: dict[str, Any]) -> SensorOutputMetadata:
        image_type = str(item.get("image_type", "photo"))
        return SensorOutputMetadata(
            entities=build_entity_hints(item),
            tags=[t for t in ("photo_library", image_type, item.get("extension", "")) if t],
            relation_candidates=build_relation_candidates(item),
        )
