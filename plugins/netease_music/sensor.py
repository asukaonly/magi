"""Timeline sensor for NetEase Cloud Music."""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from magi.awareness import (
    SensorBase,
    ContentBlock,
    SensorMemoryPolicy,
    SensorOutput,
    SensorSyncContext,
    SensorSyncResult,
)
from magi.awareness.sensor_output import SensorOutputMetadata
from .normalizers import build_netease_url
from .reader import DEFAULT_DB_PATH, NeteaseMusicReader

logger = logging.getLogger(__name__)

_LASTFM_API_URL = "http://ws.audioscrobbler.com/2.0/"


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

    def __init__(
        self,
        *,
        retention_mode: str | None = None,
        source_path: str | None = None,
        min_play_duration: int = 20,
        reader: NeteaseMusicReader | None = None,
        tag_strategy: str = "off",
        lastfm_api_key: str = "",
    ) -> None:
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
        self.source_path = source_path
        self.min_play_duration = min_play_duration
        self._reader = reader or NeteaseMusicReader()
        # Tag extraction strategy: "off" | "builtin" | "lastfm"
        self.tag_strategy = tag_strategy
        self.lastfm_api_key = lastfm_api_key
        # In-process cache keyed by "artist|track" to avoid redundant Last.fm calls
        self._lastfm_cache: dict[str, list[str]] = {}

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
        alias_list: list[str] = list(item.get("track_alias") or [])

        # Display title: "歌名 - 歌手"
        title = f"{track_name} - {artist_name}" if artist_name else track_name

        # Duration as rounded minutes (min 1) for natural language
        duration_min = max(1, round(play_duration_sec / 60))

        # Natural language summary — keeps artist, album, alias in the L1 content
        # field so that BM25 and vector recall can all match on them.
        first_alias = alias_list[0] if alias_list else ""
        if artist_name and first_alias:
            summary = self.t(
                "summary.listened_with_alias",
                track_name=track_name,
                artist_name=artist_name,
                alias=first_alias,
                duration_min=duration_min,
                fallback=f"在网易云音乐听了{artist_name}的《{track_name}》（{first_alias}），播放了{duration_min}分钟",
            )
        elif artist_name and album_name:
            summary = self.t(
                "summary.listened",
                track_name=track_name,
                artist_name=artist_name,
                album_name=album_name,
                duration_min=duration_min,
                fallback=f"在网易云音乐听了{artist_name}的《{track_name}》（{album_name}），播放了{duration_min}分钟",
            )
        elif artist_name:
            summary = self.t(
                "summary.listened_no_album",
                track_name=track_name,
                artist_name=artist_name,
                duration_min=duration_min,
                fallback=f"在网易云音乐听了{artist_name}的《{track_name}》，播放了{duration_min}分钟",
            )
        else:
            summary = self.t(
                "summary.listened_no_artist",
                track_name=track_name,
                duration_min=duration_min,
                fallback=f"在网易云音乐听了《{track_name}》，播放了{duration_min}分钟",
            )

        # Content blocks: individual fields as L2 context anchors
        content_blocks: list[ContentBlock] = []
        if track_name:
            content_blocks.append(ContentBlock(kind="text", value=track_name))
        if artist_name:
            content_blocks.append(ContentBlock(kind="text", value=artist_name))
        if album_name:
            content_blocks.append(ContentBlock(kind="text", value=album_name))
        for alias in alias_list:
            content_blocks.append(ContentBlock(kind="text", value=alias))

        # Base classification tags (genre tags added in extract_metadata)
        tags = ["netease_music", "music", "listening"]
        if item.get("is_liked"):
            tags.append("liked")

        provenance: dict[str, Any] = {
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
            "track_alias": alias_list,
        }

        # Normalize timestamp: Windows stores millis, macOS stores seconds
        occurred_at = float(item.get("update_time", 0.0))
        if occurred_at > 1e12:
            occurred_at = occurred_at / 1000

        return self._build_output(
            source_item_id=self.source_item_identity(item),
            title=title,
            summary=summary,
            occurred_at=occurred_at,
            content_blocks=content_blocks,
            tags=tags,
            provenance=provenance,
            domain_payload={"retention_mode": self.retention_mode},
        )

    async def extract_metadata(self, item: dict) -> SensorOutputMetadata:
        """Extract entity hints, relation candidates, and genre tags."""
        track_name = str(item.get("track_name", ""))
        artist_name = str(item.get("artist_name", ""))

        # Entity hints for L2 Phase 1 anchor injection
        entities: list[dict[str, Any]] = []
        if track_name:
            entities.append({
                "mention_text": track_name,
                "entity_type": "media",
                "canonical_name_hint": track_name,
            })
        if artist_name:
            entities.append({
                "mention_text": artist_name,
                "entity_type": "person",
                "canonical_name_hint": artist_name,
            })

        # Direct-write LISTENED edge (rule-based, no LLM needed)
        relation_candidates: list[dict[str, Any]] = []
        if track_name:
            relation_candidates.append({
                "predicate": "LISTENED",
                "object_id": f"media:{track_name}",
                "object_type": "media",
                "confidence": 1.0,
                "fact_kind": "interaction_evidence",
            })

        # Genre/style tags from configured strategy
        genre_tags = await self._extract_genre_tags(item)

        return SensorOutputMetadata(
            entities=entities,
            tags=genre_tags,
            relation_candidates=relation_candidates,
        )

    # ------------------------------------------------------------------
    # Tag extraction helpers
    # ------------------------------------------------------------------

    async def _extract_genre_tags(self, item: dict) -> list[str]:
        """Return genre/style tags according to the configured strategy."""
        if self.tag_strategy == "builtin":
            # Use track alias strings as contextual tag signals.
            # Coverage depends on local cache; alias is often empty for older records.
            alias_list: list[str] = list(item.get("track_alias") or [])
            return alias_list
        if self.tag_strategy == "lastfm" and self.lastfm_api_key:
            artist = str(item.get("artist_name", ""))
            track = str(item.get("track_name", ""))
            return await self._fetch_lastfm_tags(artist, track)
        return []

    async def _fetch_lastfm_tags(self, artist: str, track: str) -> list[str]:
        """Query Last.fm track.getTopTags (and artist.getTopTags as fallback).

        Results are cached in memory for the lifetime of the sensor instance
        to avoid duplicate API calls during batch syncs.
        """
        if not artist or not track:
            return []

        cache_key = f"{artist.lower()}|{track.lower()}"
        if cache_key in self._lastfm_cache:
            return self._lastfm_cache[cache_key]

        tags: list[str] = []
        try:
            import aiohttp

            params_track = {
                "method": "track.gettoptags",
                "artist": artist,
                "track": track,
                "api_key": self.lastfm_api_key,
                "autocorrect": "1",
                "format": "json",
            }
            params_artist = {
                "method": "artist.gettoptags",
                "artist": artist,
                "api_key": self.lastfm_api_key,
                "autocorrect": "1",
                "format": "json",
            }
            timeout = aiohttp.ClientTimeout(total=6)
            async with aiohttp.ClientSession() as session:
                # Track-level tags
                async with session.get(_LASTFM_API_URL, params=params_track, timeout=timeout) as resp:
                    data = await resp.json(content_type=None)
                track_tags = [
                    t["name"]
                    for t in (data.get("toptags") or {}).get("tag", [])
                    if int(t.get("count", 0)) >= 5
                ]
                tags.extend(track_tags[:5])

                # Artist-level tags as supplementary genre signal when track tags are sparse
                if len(tags) < 3:
                    async with session.get(_LASTFM_API_URL, params=params_artist, timeout=timeout) as resp2:
                        data2 = await resp2.json(content_type=None)
                    artist_tags = [
                        t["name"]
                        for t in (data2.get("toptags") or {}).get("tag", [])
                        if int(t.get("count", 0)) >= 10
                    ]
                    for at in artist_tags[:3]:
                        if at not in tags:
                            tags.append(at)

        except Exception as exc:
            logger.debug("Last.fm tag fetch failed for %s - %s: %s", artist, track, exc)

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for t in tags:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(t)

        self._lastfm_cache[cache_key] = deduped
        return deduped