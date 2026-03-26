"""Timeline sensor for NetEase Cloud Music."""
from __future__ import annotations

import hashlib
import time
from typing import Any

from magi.awareness import SensorBase, ContentBlock, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult
from .normalizers import build_netease_url
from .reader import DEFAULT_DB_PATH, NeteaseMusicReader


class NeteaseMusicTimelineSensor(SensorBase):
    """Timeline sensor for NetEase Cloud Music play records."""

    sensor_id = "timeline.netease_music"
    display_name = "NetEase Cloud Music"
    source_type = "netease_music"
    polling_mode = "interval"
    default_interval = 30
    update_key_fields = ("track_id", "update_time")
    relation_edge_whitelist = ("LISTENED",)
    supports_pull_sync = True

    memory_policy = SensorMemoryPolicy()  # defaults match design

    def __init__(self, *, retention_mode=None, source_path=None, min_play_duration=20, reader=None):
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
        self.source_path = source_path
        self.min_play_duration = min_play_duration
        self._reader = reader or NeteaseMusicReader()

    def source_item_identity(self, item: dict) -> str:
        return f"netease_{item.get('track_id')}_{item.get('update_time')}"

    def source_item_version_fingerprint(self, item: dict) -> str:
        return hashlib.sha1(
            "|".join([
                str(item.get("track_id", "")),
                str(item.get("update_time", "")),
                str(item.get("play_duration_sec", 0))
            ]).encode("utf-8")
        ).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )
        source_path = str(sensor_settings.get("source_path") or self.source_path or DEFAULT_DB_PATH)
        initial_sync_policy = str(sensor_settings.get("initial_sync_policy") or "lookback_days")
        initial_sync_lookback_days = max(1, int(sensor_settings.get("initial_sync_lookback_days", 7)))

        # Handle initial sync policy "from_now"
        if context.last_cursor is None and initial_sync_policy == "from_now":
            latest_update_time = self._reader.get_latest_update_time(source_path=source_path)
            return SensorSyncResult(
                items=[],
                next_cursor=str(latest_update_time) if latest_update_time > 0 else None,
                watermark_ts=context.last_success_at or time.time(),
                stats={
                    "count": 0,
                    "source_path": source_path,
                    "min_play_duration": self.min_play_duration,
                    "initial_sync_policy": initial_sync_policy,
                },
            )

        items = self._reader.read_play_records(
            source_path=source_path,
            min_play_duration=self.min_play_duration,
            limit=max(1, context.limit),
            last_cursor=int(context.last_cursor) if context.last_cursor else None,
        )

        next_cursor = context.last_cursor
        watermark_ts = context.last_success_at

        if items:
            # Use the highest update_time as the next cursor
            max_update_time = max(item.get("update_time", 0) for item in items)
            # Only set next_cursor if it's different from the input cursor
            next_cursor = str(max_update_time) if context.last_cursor is not None else None
            watermark_ts = max(float(item.get("update_time", 0.0)) for item in items)

        return SensorSyncResult(
            items=items,
            next_cursor=next_cursor if next_cursor != context.last_cursor else None,
            watermark_ts=watermark_ts,
            stats={
                "count": len(items),
                "source_path": source_path,
                "min_play_duration": self.min_play_duration,
                "initial_sync_policy": initial_sync_policy if context.last_cursor is None else "incremental",
            },
        )

    async def build_output(self, item: dict) -> SensorOutput:
        track_name = str(item.get("track_name", ""))
        artist_name = str(item.get("artist_name", ""))
        album_name = str(item.get("album_name", ""))
        play_duration_sec = int(item.get("play_duration_sec", 0))

        # Build title
        title = f"{track_name} - {artist_name}" if artist_name else track_name

        # Build summary (using i18n)
        summary = self.t(
            "summary.played_track",
            track_name=track_name,
            play_duration_sec=play_duration_sec,
            fallback=f"播放了 {track_name} ({play_duration_sec}秒)"
        )

        # Build content blocks
        content_blocks = []
        if track_name:
            content_blocks.append(ContentBlock(kind="text", value=track_name))
        if artist_name:
            content_blocks.append(ContentBlock(kind="text", value=artist_name))
        if album_name:
            content_blocks.append(ContentBlock(kind="text", value=album_name))

        # Build tags
        tags = ["netease_music", "music", "listening"]
        if item.get("is_liked"):
            tags.append("liked")

        # Build provenance
        provenance = {
            "sensor_id": self.sensor_id,
            "platform": "netease_music",
            "track_id": str(item.get("track_id", "")),
            "track_name": track_name,
            "track_duration_ms": int(item.get("track_duration_ms", 0)),
            "artist_id": str(item.get("artist_id", "")) or None,
            "artist_name": artist_name,
            "album_id": str(item.get("album_id", "")) or None,
            "album_name": album_name,
            "album_cover_url": str(item.get("album_cover_url", "")) or None,
            "play_source": str(item.get("source", "")),
            "play_duration_sec": play_duration_sec,
            "netease_url": build_netease_url(str(item.get("track_id", ""))),
            "is_liked": bool(item.get("is_liked", False)),
        }

        return self._build_output(
            source_item_id=self.source_item_identity(item),
            title=title,
            summary=summary,
            occurred_at=float(item.get("update_time", 0.0)),
            content_blocks=content_blocks,
            tags=tags,
            provenance=provenance,
            domain_payload={"retention_mode": self.retention_mode},
        )