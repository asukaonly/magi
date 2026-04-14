"""Timeline sensor for cross-platform media playback sessions."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from magi.awareness import ContentBlock, SensorBase, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult

from .reader import get_current_media
from .state import MediaSessionStateStore


class SystemMediaTimelineSensor(SensorBase):
    """Poll OS media state and flush completed listening sessions."""

    sensor_id = "timeline.system_media"
    display_name = "System Media"
    source_type = "system_media"
    memory_event_type = "MEDIA_LISTEN_SESSION"
    polling_mode = "interval"
    default_interval = 15
    update_key_fields = ("started_at", "app_id", "title")
    supports_pull_sync = True
    supports_state_flush = True

    memory_policy = SensorMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=False,
        tom_depth="none",
        retention_class="compressible",
        importance_bias=0.4,
        author_type="external",
        content_type="observation",
    )

    def __init__(self, *, state_store: MediaSessionStateStore | None = None) -> None:
        super().__init__()
        self._state_store = state_store or MediaSessionStateStore()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def source_item_identity(self, item: dict[str, Any]) -> str:
        return f"media:{item.get('started_at', '')}:{item.get('app_id', '')}:{item.get('title', '')}"

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        parts = [
            str(item.get("started_at", "")),
            str(item.get("app_id", "")),
            str(item.get("title", "")),
            str(item.get("duration_seconds", 0)),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        now = self._now()

        # 1. Poll current OS media state and feed into state store
        media = await get_current_media()
        await self._state_store.apply_poll(
            runtime_paths=context.runtime_paths,
            media=media,
            now=now,
        )

        # 2. Flush completed sessions
        items = await self._state_store.flush_completed(runtime_paths=context.runtime_paths)
        items.sort(key=lambda i: i.get("started_at", ""), reverse=True)

        return SensorSyncResult(
            items=items,
            next_cursor=str(now.timestamp()),
            watermark_ts=now.timestamp(),
            stats={"count": len(items)},
        )

    async def flush_runtime_state(self, *, runtime_paths: Any, plugin_settings: dict[str, Any]) -> dict[str, Any]:
        _ = plugin_settings
        return await self._state_store.flush_in_progress(runtime_paths=runtime_paths, now=self._now())

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        started_at = datetime.fromisoformat(str(item["started_at"]))
        duration_seconds = int(item.get("duration_seconds", 0))
        title = str(item.get("title", ""))
        artist = str(item.get("artist", ""))
        album = str(item.get("album", ""))
        app_name = str(item.get("app_name", ""))
        app_id = str(item.get("app_id", ""))

        duration_minutes = max(1, round(duration_seconds / 60))

        if artist:
            headline = f"Listened to '{title}' by {artist} for {duration_minutes}m"
            summary = f"Played '{title}' by {artist}"
        else:
            headline = f"Listened to '{title}' for {duration_minutes}m"
            summary = f"Played '{title}'"
        if app_name:
            summary += f" ({app_name})"
        summary += f" for {duration_minutes} minute{'s' if duration_minutes != 1 else ''}."

        blocks = [
            ContentBlock(kind="text", value=f"Track: {title}"),
        ]
        if artist:
            blocks.append(ContentBlock(kind="text", value=f"Artist: {artist}"))
        if album:
            blocks.append(ContentBlock(kind="text", value=f"Album: {album}"))
        blocks.append(ContentBlock(kind="text", value=f"App: {app_name or app_id}"))
        blocks.append(ContentBlock(kind="text", value=f"Duration: {duration_seconds}s"))

        return self._build_output(
            source_item_id=self.source_item_identity(item),
            title=headline,
            summary=summary,
            occurred_at=started_at.timestamp(),
            content_blocks=blocks,
            tags=["media", "music", "listening"],
            provenance={
                "sensor_id": self.sensor_id,
                "app_name": app_name,
                "app_id": app_id,
                "title": title,
                "artist": artist,
                "album": album,
                "started_at": str(item.get("started_at", "")),
                "ended_at": str(item.get("ended_at", "")),
            },
            domain_payload={
                "retention_mode": "analyze_only",
                "title": title,
                "artist": artist,
                "album": album,
                "app_name": app_name,
                "app_id": app_id,
                "started_at": str(item.get("started_at", "")),
                "ended_at": str(item.get("ended_at", "")),
                "duration_seconds": duration_seconds,
            },
        )
