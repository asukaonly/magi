"""Timeline sensor for sampled frontmost-app usage."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from magi.awareness import ContentBlock, SensorBase, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult

from .reader import FrontmostAppReader


class ScreenTimeTimelineSensor(SensorBase):
    """Collect sampled frontmost-app usage and aggregate it hourly."""

    sensor_id = "timeline.screen_time"
    display_name = "App Usage"
    source_type = "screen_time"
    memory_event_type = "APP_USAGE_HOURLY"
    polling_mode = "interval"
    default_interval = 300
    update_key_fields = ("bucket_start", "bundle_id")
    supports_pull_sync = True

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

    def __init__(self, *, retention_mode: str | None = None, reader: FrontmostAppReader | None = None):
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
        self._reader = reader

    @property
    def reader(self) -> FrontmostAppReader:
        if self._reader is None:
            if sys.platform != "darwin":
                return FrontmostAppReader()
            self._reader = FrontmostAppReader()
        return self._reader

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _state_path(self, runtime_paths: Any) -> Path:
        return runtime_paths.memories_dir / "screen_time_state.json"

    def _load_state(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"last_sample": None, "open_buckets": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"last_sample": None, "open_buckets": {}}

    def _save_state(self, path: Path, state: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=True, sort_keys=True), encoding="utf-8")

    def _floor_hour(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

    def _increment_buckets(
        self,
        open_buckets: dict[str, dict[str, Any]],
        *,
        bundle_id: str,
        app_name: str,
        start_at: datetime,
        end_at: datetime,
    ) -> None:
        cursor = start_at
        while cursor < end_at:
            bucket_start = self._floor_hour(cursor)
            bucket_end = bucket_start + timedelta(hours=1)
            segment_end = min(bucket_end, end_at)
            duration = max(0, int((segment_end - cursor).total_seconds()))
            if duration <= 0:
                break

            key = f"{bucket_start.isoformat()}::{bundle_id}"
            bucket = open_buckets.setdefault(
                key,
                {
                    "bucket_start": bucket_start.isoformat(),
                    "bucket_end": bucket_end.isoformat(),
                    "bundle_id": bundle_id,
                    "app_name": app_name,
                    "duration_seconds": 0,
                    "sample_count": 0,
                },
            )
            bucket["duration_seconds"] += duration
            bucket["sample_count"] += 1
            cursor = segment_end

    def source_item_identity(self, item: dict[str, Any]) -> str:
        return f"app_usage:{item.get('bucket_start', '')}:{item.get('bundle_id', '')}"

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        version_parts = [
            str(item.get("bucket_start", "")),
            str(item.get("bundle_id", "")),
            str(item.get("duration_seconds", 0)),
            str(item.get("sample_count", 0)),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        state_path = self._state_path(context.runtime_paths)
        state = self._load_state(state_path)
        open_buckets = dict(state.get("open_buckets") or {})
        now = self._now()
        current_sample = self.reader.read_frontmost_app()

        last_sample = state.get("last_sample")
        if isinstance(last_sample, dict) and last_sample.get("bundle_id") and last_sample.get("observed_at"):
            try:
                start_at = datetime.fromisoformat(str(last_sample["observed_at"]))
                if start_at.tzinfo is None:
                    start_at = start_at.replace(tzinfo=timezone.utc)
                if now > start_at:
                    self._increment_buckets(
                        open_buckets,
                        bundle_id=str(last_sample["bundle_id"]),
                        app_name=str(last_sample.get("app_name") or last_sample["bundle_id"]),
                        start_at=start_at,
                        end_at=now,
                    )
            except ValueError:
                pass

        completed_before = self._floor_hour(now)
        items: list[dict[str, Any]] = []
        remaining_buckets: dict[str, dict[str, Any]] = {}
        for key, bucket in open_buckets.items():
            bucket_end = datetime.fromisoformat(str(bucket["bucket_end"]))
            if bucket_end.tzinfo is None:
                bucket_end = bucket_end.replace(tzinfo=timezone.utc)
            if bucket_end <= completed_before:
                items.append(dict(bucket))
            else:
                remaining_buckets[key] = bucket

        state = {
            "last_sample": {
                "bundle_id": current_sample.bundle_id if current_sample is not None else "",
                "app_name": current_sample.app_name if current_sample is not None else "",
                "observed_at": now.isoformat(),
            },
            "open_buckets": remaining_buckets,
        }
        self._save_state(state_path, state)

        items.sort(key=lambda item: (item.get("bucket_start", ""), item.get("bundle_id", "")), reverse=True)
        now_ts = now.timestamp()
        return SensorSyncResult(
            items=items,
            next_cursor=str(now_ts),
            watermark_ts=now_ts,
            stats={
                "count": len(items),
                "current_app": current_sample.app_name if current_sample is not None else None,
            },
        )

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        bucket_start = datetime.fromisoformat(str(item["bucket_start"]))
        bucket_end = datetime.fromisoformat(str(item["bucket_end"]))
        duration_seconds = int(item.get("duration_seconds", 0))
        sample_count = int(item.get("sample_count", 0))
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
                ContentBlock(kind="text", value=f"Samples: {sample_count}"),
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
                "retention_mode": self.retention_mode,
                "bucket_start": bucket_start.isoformat(),
                "bucket_end": bucket_end.isoformat(),
                "bundle_id": bundle_id,
                "app_name": app_name,
                "duration_seconds": duration_seconds,
                "sample_count": sample_count,
                "source": "lsappinfo",
            },
        )
