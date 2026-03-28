"""Timeline sensor for event-driven frontmost-app usage."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from magi.awareness import ContentBlock, SensorBase, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult

from .state import ScreenTimeStateStore


class ScreenTimeTimelineSensor(SensorBase):
    """Flush event-driven frontmost-app usage buckets into hourly aggregates."""

    sensor_id = "timeline.screen_time"
    display_name = "App Usage"
    source_type = "screen_time"
    memory_event_type = "APP_USAGE_HOURLY"
    polling_mode = "interval"
    default_interval = 300
    update_key_fields = ("bucket_start", "bundle_id")
    supports_pull_sync = True
    supports_state_flush = True

    memory_policy = SensorMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=False,
        tom_depth="none",
        retention_class="compressible",
        importance_bias=0.3,
        author_type="external",
        content_type="observation",
    )

    def __init__(self, *, state_store: ScreenTimeStateStore | None = None):
        super().__init__()
        self._state_store = state_store or ScreenTimeStateStore()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def source_item_identity(self, item: dict[str, Any]) -> str:
        return f"app_usage:{item.get('bucket_start', '')}:{item.get('bundle_id', '')}"

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        version_parts = [
            str(item.get("bucket_start", "")),
            str(item.get("bundle_id", "")),
            str(item.get("duration_seconds", 0)),
            str(item.get("session_count", 0)),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        now = self._now()
        items = await self._state_store.flush_completed(runtime_paths=context.runtime_paths, now=now)
        items.sort(key=lambda item: (item.get("bucket_start", ""), item.get("bundle_id", "")), reverse=True)
        now_ts = now.timestamp()
        return SensorSyncResult(
            items=items,
            next_cursor=str(now_ts),
            watermark_ts=now_ts,
            stats={"count": len(items)},
        )

    async def flush_runtime_state(self, *, runtime_paths: Any, plugin_settings: dict[str, Any]) -> dict[str, Any]:
        _ = plugin_settings
        return await self._state_store.flush_in_progress(runtime_paths=runtime_paths, now=self._now())

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        bucket_start = datetime.fromisoformat(str(item["bucket_start"]))
        bucket_end = datetime.fromisoformat(str(item["bucket_end"]))
        duration_seconds = int(item.get("duration_seconds", 0))
        session_count = int(item.get("session_count", 0))
        bundle_id = str(item.get("bundle_id", ""))
        app_name = str(item.get("app_name", bundle_id or "Unknown App"))

        duration_minutes = max(1, round(duration_seconds / 60))
        title = f"{app_name} active for {duration_minutes}m"
        summary = (
            f"{app_name} was frontmost for {duration_minutes}m "
            f"during {bucket_start.strftime('%H:%M')}-{bucket_end.strftime('%H:%M')}."
        )

        return self._build_output(
            source_item_id=self.source_item_identity(item),
            title=title,
            summary=summary,
            occurred_at=bucket_start.timestamp(),
            content_blocks=[
                ContentBlock(kind="text", value=f"App: {app_name}"),
                ContentBlock(kind="text", value=f"Bundle ID: {bundle_id}"),
                ContentBlock(kind="text", value=f"Bucket: {bucket_start.isoformat()} to {bucket_end.isoformat()}"),
                ContentBlock(kind="text", value=f"Duration: {duration_seconds} seconds"),
                ContentBlock(kind="text", value=f"Sessions: {session_count}"),
            ],
            tags=["screen_time", "app_usage", "hourly"],
            provenance={
                "sensor_id": self.sensor_id,
                "bucket_start": bucket_start.isoformat(),
                "bucket_end": bucket_end.isoformat(),
                "bundle_id": bundle_id,
                "app_name": app_name,
            },
            domain_payload={
                "retention_mode": "analyze_only",
                "bucket_start": bucket_start.isoformat(),
                "bucket_end": bucket_end.isoformat(),
                "bundle_id": bundle_id,
                "app_name": app_name,
                "duration_seconds": duration_seconds,
                "session_count": session_count,
                "source": "plugin_ingress",
            },
        )
