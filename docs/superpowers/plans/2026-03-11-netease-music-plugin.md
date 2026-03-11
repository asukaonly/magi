# NetEase Cloud Music Plugin Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a timeline sensor plugin that captures NetEase Cloud Music play history from the local SQLite database.

**Architecture:** Follow chrome-history plugin pattern - reader copies DB to temp location, sensor joins playingCount with historyTracks tables, normalizer parses JSON metadata. Use updateTime as cursor for incremental sync.

**Tech Stack:** Python, SQLite, TimelineSensorBase, Plugin framework

---

## File Structure

```
plugins/
└── netease-music/
    ├── plugin.toml          # Plugin metadata
    ├── plugin.py            # Entry point, registers sensor
    ├── sensor.py            # TimelineSensorBase implementation
    ├── reader.py            # SQLite database reader
    └── normalizers.py       # JSON parsing, data helpers

backend/tests/
└── test_netease_music_plugin.py  # Plugin tests
```

---

## Chunk 1: Normalizers Module

### Task 1.1: Create normalizers.py

**Files:**
- Create: `plugins/netease-music/normalizers.py`
- Test: `backend/tests/test_netease_music_plugin.py`

- [ ] **Step 1: Create normalizers.py with helper functions**

```python
"""Normalization helpers for NetEase Cloud Music timeline ingestion."""
from __future__ import annotations

from typing import Any


def parse_track_json(json_str: str | None) -> dict[str, Any]:
    """Parse track JSON string into a dictionary."""
    import json
    if not json_str:
        return {}
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}


def extract_track_info(track_data: dict[str, Any]) -> dict[str, Any]:
    """Extract normalized track info from parsed JSON."""
    artists = track_data.get("artists") or []
    artist = artists[0] if artists else {}
    album = track_data.get("album") or {}

    return {
        "track_id": str(track_data.get("id") or ""),
        "track_name": str(track_data.get("name") or ""),
        "track_duration_ms": int(track_data.get("duration") or 0),
        "artist_id": str(artist.get("id") or ""),
        "artist_name": str(artist.get("name") or ""),
        "album_id": str(album.get("id") or ""),
        "album_name": str(album.get("name") or ""),
        "album_cover_url": str(album.get("picUrl") or ""),
    }


def build_netease_url(track_id: str) -> str:
    """Build NetEase Cloud Music URL for a track."""
    return f"https://music.163.com/#/song?id={track_id}"
```

- [ ] **Step 2: Write tests for normalizers**

```python
# In backend/tests/test_netease_music_plugin.py
"""Tests for NetEase Cloud Music plugin."""
import pytest
from plugins.netease_music.normalizers import (
    parse_track_json,
    extract_track_info,
    build_netease_url,
)


class TestParseTrackJson:
    def test_parse_valid_json(self):
        json_str = '{"id": "123", "name": "Test Song"}'
        result = parse_track_json(json_str)
        assert result == {"id": "123", "name": "Test Song"}

    def test_parse_empty_string(self):
        result = parse_track_json("")
        assert result == {}

    def test_parse_none(self):
        result = parse_track_json(None)
        assert result == {}

    def test_parse_invalid_json(self):
        result = parse_track_json("not valid json")
        assert result == {}


class TestExtractTrackInfo:
    def test_extract_full_info(self):
        track_data = {
            "id": "101120",
            "name": "伶仃谣",
            "duration": 255893,
            "artists": [{"id": "3249", "name": "河图"}],
            "album": {"id": "9896", "name": "风起天阑", "picUrl": "http://example.com/cover.jpg"},
        }
        result = extract_track_info(track_data)
        assert result["track_id"] == "101120"
        assert result["track_name"] == "伶仃谣"
        assert result["track_duration_ms"] == 255893
        assert result["artist_id"] == "3249"
        assert result["artist_name"] == "河图"
        assert result["album_id"] == "9896"
        assert result["album_name"] == "风起天阑"
        assert result["album_cover_url"] == "http://example.com/cover.jpg"

    def test_extract_missing_artists(self):
        track_data = {"id": "123", "name": "Test"}
        result = extract_track_info(track_data)
        assert result["artist_id"] == ""
        assert result["artist_name"] == ""

    def test_extract_missing_album(self):
        track_data = {"id": "123", "name": "Test", "artists": [{"id": "1", "name": "Artist"}]}
        result = extract_track_info(track_data)
        assert result["album_id"] == ""
        assert result["album_name"] == ""


class TestBuildNeteaseUrl:
    def test_build_url(self):
        url = build_netease_url("101120")
        assert url == "https://music.163.com/#/song?id=101120"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_netease_music_plugin.py -v`
Expected: FAIL with module import error

- [ ] **Step 4: Create plugin directory and __init__.py**

```bash
mkdir -p plugins/netease-music
touch plugins/netease-music/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_netease_music_plugin.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/netease-music/ backend/tests/test_netease_music_plugin.py
git commit -m "feat(netease-music): add normalizers module with tests"
```

---

## Chunk 2: Database Reader

### Task 2.1: Create reader.py

**Files:**
- Create: `plugins/netease-music/reader.py`
- Modify: `backend/tests/test_netease_music_plugin.py`

- [ ] **Step 1: Write failing tests for reader**

```python
# Add to backend/tests/test_netease_music_plugin.py
import tempfile
import sqlite3
from pathlib import Path
from plugins.netease_music.reader import NeteaseMusicReader


class TestNeteaseMusicReader:
    @pytest.fixture
    def temp_db(self, tmp_path: Path):
        """Create a temporary test database."""
        db_path = tmp_path / "sqlite_storage.sqlite3"
        conn = sqlite3.connect(str(db_path))

        # Create tables
        conn.execute("""
            CREATE TABLE playingCount (
                resourceId VARCHAR(40),
                playDuration BIGINT,
                updateTime BIGINT,
                source VARCHAR(40),
                uid VARCHAR(40),
                resourceType VARCHAR(40),
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jsonStr TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE historyTracks (
                playtime BIGINT,
                id VARCHAR(40) PRIMARY KEY,
                jsonStr TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE web_playlist (
                pid INTEGER PRIMARY KEY,
                playlist TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE web_playlist_track (
                pid INTEGER,
                tid INTEGER,
                version INTEGER,
                \`order\` INTEGER
            )
        """)

        # Insert test data
        conn.execute("""
            INSERT INTO playingCount (resourceId, playDuration, updateTime, source, uid, resourceType)
            VALUES ('123', 100, 1700000000000, 'playlist', 'user1', 'track')
        """)
        conn.execute("""
            INSERT INTO playingCount (resourceId, playDuration, updateTime, source, uid, resourceType)
            VALUES ('456', 5, 1700000001000, 'userfm', 'user1', 'track')
        """)  # Too short, should be filtered
        conn.execute("""
            INSERT INTO playingCount (resourceId, playDuration, updateTime, source, uid, resourceType)
            VALUES ('789', 200, 1700000002000, 'search', 'user1', 'track')
        """)
        conn.execute("""
            INSERT INTO historyTracks (playtime, id, jsonStr)
            VALUES (1700000000000, '123', '{"id":"123","name":"Song A","duration":180000,"artists":[{"id":"1","name":"Artist A"}],"album":{"id":"10","name":"Album A"}}')
        """)
        conn.execute("""
            INSERT INTO historyTracks (playtime, id, jsonStr)
            VALUES (1700000002000, '789', '{"id":"789","name":"Song B","duration":240000,"artists":[{"id":"2","name":"Artist B"}],"album":{"id":"20","name":"Album B"}}')
        """)
        conn.execute("""
            INSERT INTO web_playlist (pid, playlist)
            VALUES (100, '{"name":"我喜欢的音乐","specialType":5,"trackCount":1}')
        """)
        conn.execute("""
            INSERT INTO web_playlist_track (pid, tid, version, \`order\`)
            VALUES (100, 123, 1, 0)
        """)

        conn.commit()
        conn.close()
        return db_path

    def test_resolve_db_path(self, temp_db: Path):
        reader = NeteaseMusicReader()
        resolved = reader.resolve_db_path(str(temp_db))
        assert resolved.exists()

    def test_get_liked_playlist_id(self, temp_db: Path):
        reader = NeteaseMusicReader()
        conn = sqlite3.connect(str(temp_db))
        try:
            playlist_id = reader.get_liked_playlist_id(conn)
            assert playlist_id == 100
        finally:
            conn.close()

    def test_get_liked_track_ids(self, temp_db: Path):
        reader = NeteaseMusicReader()
        conn = sqlite3.connect(str(temp_db))
        try:
            track_ids = reader.get_liked_track_ids(conn, 100)
            assert track_ids == {"123"}
        finally:
            conn.close()

    def test_read_play_records_filters_duration(self, temp_db: Path):
        reader = NeteaseMusicReader()
        records = reader.read_play_records(
            source_path=str(temp_db),
            min_play_duration=20,
            limit=100,
        )
        # Should have 2 records (filtered out the 5 second one)
        assert len(records) == 2

    def test_read_play_records_includes_track_info(self, temp_db: Path):
        reader = NeteaseMusicReader()
        records = reader.read_play_records(
            source_path=str(temp_db),
            min_play_duration=20,
            limit=100,
        )
        # Check first record has track info joined
        record = records[0]
        assert record["track_id"] == "123"
        assert record["track_name"] == "Song A"
        assert record["artist_name"] == "Artist A"

    def test_read_play_records_marks_liked(self, temp_db: Path):
        reader = NeteaseMusicReader()
        records = reader.read_play_records(
            source_path=str(temp_db),
            min_play_duration=20,
            limit=100,
        )
        # Track 123 is liked, 789 is not
        liked_record = next(r for r in records if r["resource_id"] == "123")
        not_liked_record = next(r for r in records if r["resource_id"] == "789")
        assert liked_record["is_liked"] is True
        assert not_liked_record["is_liked"] is False

    def test_read_play_records_with_cursor(self, temp_db: Path):
        reader = NeteaseMusicReader()
        # First read
        records = reader.read_play_records(
            source_path=str(temp_db),
            min_play_duration=20,
            limit=1,
        )
        assert len(records) == 1
        cursor = records[0]["update_time"]

        # Second read with cursor
        records2 = reader.read_play_records(
            source_path=str(temp_db),
            min_play_duration=20,
            limit=100,
            last_cursor=str(cursor),
        )
        assert len(records2) == 1
        assert records2[0]["resource_id"] == "789"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_netease_music_plugin.py::TestNeteaseMusicReader -v`
Expected: FAIL with module import error

- [ ] **Step 3: Implement reader.py**

```python
"""Read NetEase Cloud Music play history from local SQLite database."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .normalizers import extract_track_info, parse_track_json

DEFAULT_DB_PATH = "~/Library/Containers/com.netease.163music/Data/Documents/storage/sqlite_storage.sqlite3"


class NeteaseMusicReader:
    """Read and normalize NetEase Cloud Music play history."""

    def resolve_db_path(self, source_path: str | None = None) -> Path:
        """Resolve the database file path."""
        path = Path(source_path or DEFAULT_DB_PATH).expanduser()
        return path

    def _copy_database(self, source_path: str | None = None) -> Path:
        """Copy database to temp location to avoid lock issues."""
        db_path = self.resolve_db_path(source_path)
        if not db_path.exists():
            raise FileNotFoundError(f"NetEase database not found: {db_path}")
        temp_dir = Path(tempfile.mkdtemp(prefix="magi-netease-music-"))
        copy_path = temp_dir / "sqlite_storage.sqlite3"
        shutil.copy2(db_path, copy_path)
        return copy_path

    def get_liked_playlist_id(self, conn: sqlite3.Connection) -> int | None:
        """Find the liked songs playlist ID (specialType = 5)."""
        cursor = conn.execute("""
            SELECT pid
            FROM web_playlist
            WHERE json_extract(playlist, '$.specialType') = 5
            ORDER BY json_extract(playlist, '$.trackCount') DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return row[0] if row else None

    def get_liked_track_ids(self, conn: sqlite3.Connection, playlist_id: int) -> set[str]:
        """Get set of liked track IDs from a playlist."""
        cursor = conn.execute(
            "SELECT tid FROM web_playlist_track WHERE pid = ?",
            (playlist_id,),
        )
        return {str(row[0]) for row in cursor.fetchall()}

    def read_play_records(
        self,
        *,
        source_path: str | None = None,
        min_play_duration: int = 20,
        limit: int = 200,
        last_cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read play records with track info and liked status."""
        copy_path = self._copy_database(source_path)
        try:
            conn = sqlite3.connect(str(copy_path))
            try:
                return self._query_play_records(
                    conn=conn,
                    min_play_duration=min_play_duration,
                    limit=limit,
                    last_cursor=last_cursor,
                )
            finally:
                conn.close()
        finally:
            shutil.rmtree(copy_path.parent, ignore_errors=True)

    def _query_play_records(
        self,
        *,
        conn: sqlite3.Connection,
        min_play_duration: int,
        limit: int,
        last_cursor: str | None,
    ) -> list[dict[str, Any]]:
        # Get liked playlist and track IDs
        liked_playlist_id = self.get_liked_playlist_id(conn)
        liked_track_ids = set()
        if liked_playlist_id:
            liked_track_ids = self.get_liked_track_ids(conn, liked_playlist_id)

        # Build query
        last_update_time = int(last_cursor) if last_cursor and last_cursor.isdigit() else 0

        cursor = conn.execute(
            """
            SELECT
                pc.resourceId,
                pc.playDuration,
                pc.updateTime,
                pc.source,
                ht.jsonStr
            FROM playingCount pc
            LEFT JOIN historyTracks ht ON pc.resourceId = ht.id
            WHERE pc.playDuration >= ?
              AND pc.resourceType = 'track'
              AND pc.updateTime > ?
              AND ht.id IS NOT NULL
            ORDER BY pc.updateTime ASC
            LIMIT ?
            """,
            (min_play_duration, last_update_time, limit),
        )

        records: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            resource_id = str(row[0])
            play_duration = int(row[1] or 0)
            update_time = int(row[2] or 0)
            source = str(row[3] or "")
            track_json = str(row[4] or "")

            track_data = parse_track_json(track_json)
            track_info = extract_track_info(track_data)

            records.append({
                "resource_id": resource_id,
                "play_duration_sec": play_duration,
                "update_time": update_time,
                "play_source": source,
                "is_liked": resource_id in liked_track_ids,
                **track_info,
            })

        return records

    def get_latest_update_time(self, *, source_path: str | None = None) -> int:
        """Get the latest updateTime from playingCount."""
        copy_path = self._copy_database(source_path)
        try:
            conn = sqlite3.connect(str(copy_path))
            try:
                cursor = conn.execute(
                    "SELECT COALESCE(MAX(updateTime), 0) FROM playingCount"
                )
                row = cursor.fetchone()
                return int(row[0] or 0) if row else 0
            finally:
                conn.close()
        finally:
            shutil.rmtree(copy_path.parent, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_netease_music_plugin.py::TestNeteaseMusicReader -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/netease-music/reader.py backend/tests/test_netease_music_plugin.py
git commit -m "feat(netease-music): add database reader with tests"
```

---

## Chunk 3: Sensor Implementation

### Task 3.1: Create sensor.py

**Files:**
- Create: `plugins/netease-music/sensor.py`
- Modify: `backend/tests/test_netease_music_plugin.py`

- [ ] **Step 1: Write failing tests for sensor**

```python
# Add to backend/tests/test_netease_music_plugin.py
from unittest.mock import MagicMock, patch
from magi.timeline import SensorSyncContext, SensorSyncResult
from plugins.netease_music.sensor import NeteaseMusicTimelineSensor


class TestNeteaseMusicTimelineSensor:
    @pytest.fixture
    def mock_reader(self):
        reader = MagicMock()
        reader.read_play_records.return_value = [
            {
                "resource_id": "123",
                "play_duration_sec": 100,
                "update_time": 1700000000000,
                "play_source": "playlist",
                "is_liked": True,
                "track_id": "123",
                "track_name": "Song A",
                "track_duration_ms": 180000,
                "artist_id": "1",
                "artist_name": "Artist A",
                "album_id": "10",
                "album_name": "Album A",
                "album_cover_url": "http://example.com/cover.jpg",
            }
        ]
        return reader

    def test_sensor_id(self):
        sensor = NeteaseMusicTimelineSensor()
        assert sensor.sensor_id == "timeline.netease_music"

    def test_source_item_identity(self):
        sensor = NeteaseMusicTimelineSensor()
        item = {"resource_id": "123", "update_time": 1700000000000}
        identity = sensor.source_item_identity(item)
        assert identity == "netease_123_1700000000000"

    def test_collect_items_returns_records(self, mock_reader):
        sensor = NeteaseMusicTimelineSensor(reader=mock_reader)
        context = SensorSyncContext(
            plugin_settings={},
            last_cursor=None,
            last_success_at=1700000000000,
            limit=100,
        )
        result = asyncio.run(sensor.collect_items(context))
        assert isinstance(result, SensorSyncResult)
        assert len(result.items) == 1
        assert result.items[0]["resource_id"] == "123"

    def test_build_timeline_event(self, mock_reader):
        sensor = NeteaseMusicTimelineSensor(reader=mock_reader)
        item = {
            "resource_id": "123",
            "play_duration_sec": 100,
            "update_time": 1700000000000,
            "play_source": "playlist",
            "is_liked": True,
            "track_id": "123",
            "track_name": "Song A",
            "track_duration_ms": 180000,
            "artist_id": "1",
            "artist_name": "Artist A",
            "album_id": "10",
            "album_name": "Album A",
            "album_cover_url": "http://example.com/cover.jpg",
        }
        event = asyncio.run(sensor.build_timeline_event(item))
        assert event.title == "Song A - Artist A"
        assert "Song A" in event.summary
        assert "netease_music" in event.tags
        assert "liked" in event.tags
        assert event.provenance["track_id"] == "123"
        assert event.provenance["play_duration_sec"] == 100

    def test_build_timeline_event_not_liked(self, mock_reader):
        sensor = NeteaseMusicTimelineSensor(reader=mock_reader)
        item = {
            "resource_id": "456",
            "play_duration_sec": 50,
            "update_time": 1700000001000,
            "play_source": "userfm",
            "is_liked": False,
            "track_id": "456",
            "track_name": "Song B",
            "track_duration_ms": 200000,
            "artist_id": "2",
            "artist_name": "Artist B",
            "album_id": "20",
            "album_name": "Album B",
            "album_cover_url": "",
        }
        event = asyncio.run(sensor.build_timeline_event(item))
        assert "liked" not in event.tags


import asyncio
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_netease_music_plugin.py::TestNeteaseMusicTimelineSensor -v`
Expected: FAIL with module import error

- [ ] **Step 3: Implement sensor.py**

```python
"""Timeline sensor for NetEase Cloud Music play history."""
from __future__ import annotations

import time
from typing import Any

from magi.timeline import SensorSyncContext, SensorSyncResult, TimelineContentBlock, TimelineEvent
from magi.timeline.sensors import TimelineSensorBase

from .normalizers import build_netease_url
from .reader import DEFAULT_DB_PATH, NeteaseMusicReader


class NeteaseMusicTimelineSensor(TimelineSensorBase):
    """Timeline sensor backed by NetEase Cloud Music local database."""

    sensor_id = "timeline.netease_music"
    display_name = "NetEase Cloud Music"
    source_type = "netease_music"
    polling_mode = "interval"
    default_interval = 30
    update_key_fields = ("resource_id", "update_time")
    relation_edge_whitelist = ("LISTENED",)
    supports_pull_sync = True

    def __init__(
        self,
        *,
        retention_mode: str | None = None,
        source_path: str | None = None,
        min_play_duration: int = 20,
        reader: NeteaseMusicReader | None = None,
    ) -> None:
        super().__init__(
            retention_mode=retention_mode,
            source_path=source_path,
        )
        self.min_play_duration = min_play_duration
        self._reader = reader or NeteaseMusicReader()

    def source_item_identity(self, item: dict[str, Any]) -> str:
        return f"netease_{item.get('resource_id')}_{item.get('update_time')}"

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        return "|".join([
            str(item.get("resource_id") or ""),
            str(item.get("update_time") or ""),
            str(item.get("play_duration_sec") or 0),
        ])

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )
        source_path = str(
            sensor_settings.get("db_path") or self.source_path or DEFAULT_DB_PATH
        )
        min_play_duration = int(
            sensor_settings.get("min_play_duration", self.min_play_duration)
        )

        # Handle initial sync policy
        if context.last_cursor is None:
            initial_sync_policy = str(sensor_settings.get("initial_sync_policy") or "from_now")
            if initial_sync_policy == "from_now":
                latest_time = self._reader.get_latest_update_time(source_path=source_path)
                return SensorSyncResult(
                    items=[],
                    next_cursor=str(latest_time) if latest_time > 0 else None,
                    watermark_ts=context.last_success_at or time.time(),
                    stats={
                        "count": 0,
                        "initial_sync_policy": initial_sync_policy,
                    },
                )

        items = self._reader.read_play_records(
            source_path=source_path,
            min_play_duration=min_play_duration,
            limit=max(1, context.limit),
            last_cursor=context.last_cursor,
        )

        next_cursor = context.last_cursor
        watermark_ts = context.last_success_at
        if items:
            max_update_time = max(item.get("update_time", 0) for item in items)
            next_cursor = str(max_update_time) if max_update_time > 0 else context.last_cursor
            watermark_ts = max(item.get("update_time", 0) / 1000.0 for item in items)

        return SensorSyncResult(
            items=items,
            next_cursor=str(next_cursor) if next_cursor else None,
            watermark_ts=watermark_ts,
            stats={
                "count": len(items),
            },
        )

    async def build_timeline_event(self, item: dict[str, Any]) -> TimelineEvent:
        track_name = str(item.get("track_name") or "")
        artist_name = str(item.get("artist_name") or "")
        album_name = str(item.get("album_name") or "")
        play_duration = int(item.get("play_duration_sec") or 0)
        is_liked = bool(item.get("is_liked"))

        title = f"{track_name} - {artist_name}" if track_name and artist_name else track_name or "Unknown Track"
        summary = f"播放了 {track_name}"
        if play_duration > 0:
            summary += f" ({play_duration}秒)"

        content_blocks = [
            TimelineContentBlock(kind="text", value=track_name),
        ]
        if artist_name:
            content_blocks.append(TimelineContentBlock(kind="text", value=artist_name))
        if album_name:
            content_blocks.append(TimelineContentBlock(kind="text", value=album_name))

        tags = ["netease_music", "music", "listening"]
        if is_liked:
            tags.append("liked")

        track_id = str(item.get("track_id") or item.get("resource_id") or "")

        return self._build_event(
            source_item_id=self.source_item_identity(item),
            title=title,
            summary=summary,
            occurred_at=float(item.get("update_time", 0)) / 1000.0,
            content_blocks=content_blocks,
            tags=tags,
            provenance={
                "sensor_id": self.sensor_id,
                "platform": "netease_cloud_music",
                "track_id": track_id,
                "track_name": track_name,
                "track_duration_ms": int(item.get("track_duration_ms") or 0),
                "artist_id": str(item.get("artist_id") or ""),
                "artist_name": artist_name,
                "album_id": str(item.get("album_id") or ""),
                "album_name": album_name,
                "album_cover_url": str(item.get("album_cover_url") or ""),
                "play_source": str(item.get("play_source") or ""),
                "play_duration_sec": play_duration,
                "netease_url": build_netease_url(track_id),
                "is_liked": is_liked,
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_netease_music_plugin.py::TestNeteaseMusicTimelineSensor -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/netease-music/sensor.py backend/tests/test_netease_music_plugin.py
git commit -m "feat(netease-music): add timeline sensor with tests"
```

---

## Chunk 4: Plugin Registration

### Task 4.1: Create plugin.toml

**Files:**
- Create: `plugins/netease-music/plugin.toml`

- [ ] **Step 1: Create plugin.toml**

```toml
[plugin]
id = "netease-music"
name = "NetEase Cloud Music"
version = "0.1.0"
description = "Local NetEase Cloud Music play history ingestion for the timeline."
author = "Magi Team"
entry_module = "plugin"
entry_class = "NeteaseMusicPlugin"
official = true
contribution_types = ["sensor"]
```

### Task 4.2: Create plugin.py

**Files:**
- Create: `plugins/netease-music/plugin.py`
- Modify: `backend/tests/test_netease_music_plugin.py`

- [ ] **Step 2: Write failing tests for plugin**

```python
# Add to backend/tests/test_netease_music_plugin.py
from plugins.netease_music.plugin import NeteaseMusicPlugin, DEFAULT_SETTINGS


class TestNeteaseMusicPlugin:
    def test_default_settings(self):
        assert DEFAULT_SETTINGS["enabled"] is False
        assert DEFAULT_SETTINGS["sync_mode"] == "manual"
        assert DEFAULT_SETTINGS["min_play_duration"] == 20

    def test_plugin_get_sensors(self):
        plugin = NeteaseMusicPlugin(settings={})
        sensors = plugin.get_sensors()
        assert len(sensors) == 1

        sensor_id, sensor_instance, sensor_spec = sensors[0]
        assert sensor_id == "timeline.netease_music"
        assert sensor_spec.display_name == "NetEase Cloud Music"
        assert sensor_spec.sensor_id == "timeline.netease_music"

    def test_plugin_get_sensors_with_settings(self):
        plugin = NeteaseMusicPlugin(settings={
            "sensors": {
                "netease_music": {
                    "min_play_duration": 30,
                    "sync_mode": "interval",
                }
            }
        })
        sensors = plugin.get_sensors()
        _, _, sensor_spec = sensors[0]
        assert sensor_spec.sync_mode == "interval"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_netease_music_plugin.py::TestNeteaseMusicPlugin -v`
Expected: FAIL with module import error

- [ ] **Step 4: Implement plugin.py**

```python
"""NetEase Cloud Music timeline plugin."""
from __future__ import annotations

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .reader import DEFAULT_DB_PATH
from .sensor import NeteaseMusicTimelineSensor


DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_mode": "manual",
    "sync_interval_minutes": 30,
    "min_play_duration": 20,
    "db_path": DEFAULT_DB_PATH,
    "default_retention_mode": "analyze_only",
    "storage_mode": "managed",
    "initial_sync_policy": "from_now",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enabled",
            description="Whether NetEase Cloud Music sync is active.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.db_path",
            type="path",
            label="Database Path",
            description="Path to the NetEase Cloud Music SQLite database.",
            default=DEFAULT_DB_PATH,
            section="general",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.min_play_duration",
            type="number",
            label="Min Play Duration (seconds)",
            description="Minimum play duration to include in timeline.",
            default=20,
            section="general",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_mode",
            type="select",
            label="Sync Mode",
            description="How NetEase play history should be synchronized.",
            default="manual",
            options=[
                ExtensionFieldOption(label="Manual", value="manual"),
                ExtensionFieldOption(label="Interval", value="interval"),
            ],
            section="general",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="number",
            label="Sync Interval (minutes)",
            description="Polling interval for interval-based sync.",
            default=30,
            section="general",
            surface="timeline",
            order=50,
        ),
    ]


class NeteaseMusicPlugin(Plugin):
    """Registers the NetEase Cloud Music timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("netease_music", {}))

        sensor = NeteaseMusicTimelineSensor(
            retention_mode=str(
                settings.get("default_retention_mode")
                or DEFAULT_SETTINGS["default_retention_mode"]
            ),
            source_path=str(settings.get("db_path") or DEFAULT_SETTINGS["db_path"]),
            min_play_duration=int(
                settings.get("min_play_duration", DEFAULT_SETTINGS["min_play_duration"])
            ),
        )

        return [
            (
                "timeline.netease_music",
                sensor,
                SensorSpec(
                    sensor_id="timeline.netease_music",
                    display_name="NetEase Cloud Music",
                    description="NetEase Cloud Music play history ingested into the user timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode=str(settings.get("sync_mode", DEFAULT_SETTINGS["sync_mode"])),
                    polling_mode="interval",
                    fields=_fields("sensors.netease_music"),
                    metadata={
                        "source_type": "netease_music",
                        "default_settings": dict(DEFAULT_SETTINGS),
                    },
                ),
            )
        ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_netease_music_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add plugins/netease-music/
git commit -m "feat(netease-music): add plugin registration and configuration"
```

---

## Chunk 5: Integration

### Task 5.1: Run full test suite

- [ ] **Step 1: Run all plugin tests**

Run: `cd backend && pytest tests/test_netease_music_plugin.py -v`
Expected: All tests pass

- [ ] **Step 2: Run full backend tests to ensure no regressions**

Run: `cd backend && pytest tests/ -v --ignore=tests/test_chrome_history_plugin.py`
Expected: All tests pass

### Task 5.2: Manual verification

- [ ] **Step 3: Verify plugin is discoverable**

Run: `python -c "from plugins.netease_music.plugin import NeteaseMusicPlugin; print('OK')"`
Expected: "OK"

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(netease-music): complete NetEase Cloud Music timeline plugin"
```

---

## Summary

This plan creates a complete NetEase Cloud Music timeline plugin with:

1. **normalizers.py** - JSON parsing and track info extraction
2. **reader.py** - SQLite database reader with:
   - Database copy for safe access
   - Liked playlist detection (specialType=5)
   - Play record queries with track metadata join
   - Duration filtering and incremental sync support
3. **sensor.py** - TimelineSensorBase implementation with:
   - Event building with proper tags ("liked" for favorites)
   - Incremental sync using updateTime cursor
4. **plugin.py** - Plugin registration with settings UI fields
5. **Tests** - Comprehensive test coverage for all components
