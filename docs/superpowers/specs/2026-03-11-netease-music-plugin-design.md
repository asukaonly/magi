# NetEase Cloud Music Timeline Plugin Design

## Overview

A timeline sensor plugin that captures play history from the local NetEase Cloud Music desktop application and ingests it into the user timeline.

## Data Source

### Database Location
```
~/Library/Containers/com.netease.163music/Data/Documents/storage/sqlite_storage.sqlite3
```

### Primary Tables

**1. `playingCount` - Main data source (play sessions)**
```sql
CREATE TABLE playingCount (
    resourceId VARCHAR(40),      -- Track ID
    playDuration BIGINT,        -- Actual play duration (seconds)
    updateTime BIGINT,          -- Timestamp (milliseconds)
    source VARCHAR(40),         -- Play source (e.g., "userfm", "playlist")
    uid VARCHAR(40),            -- User ID
    resourceType VARCHAR(40),   -- Resource type (e.g., "track")
    id INTEGER PRIMARY KEY,
    jsonStr TEXT
);
```

**2. `historyTracks` - Song metadata (joined by resourceId = id)**
```sql
CREATE TABLE historyTracks (
    playtime BIGINT,
    id VARCHAR(40) PRIMARY KEY,
    jsonStr TEXT  -- Contains: name, artists, album, duration, etc.
);
```

**3. `web_playlist` + `web_playlist_track` - Liked songs**
- Liked playlist identified by `specialType = 5`
- Track IDs stored in `web_playlist_track` table

## Data Flow

```
playingCount (filter playDuration > 20s)
    ↓
JOIN historyTracks (by resourceId = id)
    ↓
Skip if track not found in historyTracks
    ↓
Check if track is liked (web_playlist_track)
    ↓
Build TimelineEvent
```

## Plugin Structure

```
plugins/
└── netease-music/
    ├── plugin.toml          # Plugin metadata
    ├── plugin.py            # Entry point, sensor registration
    ├── sensor.py            # TimelineSensorBase implementation
    ├── reader.py            # SQLite database reader
    └── normalizers.py       # JSON parsing, data normalization
```

## TimelineEvent Schema

```python
TimelineEvent(
    source_item_id="netease_{resourceId}_{updateTime}",

    title="{song_name} - {artist_name}",
    summary="播放了 {song_name} ({play_duration}秒)",
    occurred_at=updateTime / 1000,

    content_blocks=[
        TimelineContentBlock(kind="text", value=song_name),
        TimelineContentBlock(kind="text", value=artist_name),
        TimelineContentBlock(kind="text", value=album_name),
    ],

    tags=["netease_music", "music", "listening", "liked"?],

    provenance={
        "sensor_id": "timeline.netease_music",
        "platform": "netease_cloud_music",
        "track_id": track_id,
        "track_name": song_name,
        "track_duration_ms": duration,
        "artist_id": artist_id,
        "artist_name": artist_name,
        "album_id": album_id,
        "album_name": album_name,
        "album_cover_url": pic_url,
        "play_source": source,
        "play_duration_sec": play_duration,
        "netease_url": f"https://music.163.com/#/song?id={track_id}",
    },
)
```

## Configuration

```python
DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_mode": "manual",
    "sync_interval_minutes": 30,
    "min_play_duration": 20,  # Minimum play duration (seconds)
    "db_path": "~/Library/Containers/com.netease.163music/Data/Documents/storage/sqlite_storage.sqlite3",
}
```

## Key Implementation Details

### Finding Liked Playlist
Dynamically query for the liked playlist (specialType = 5):
```python
def get_liked_playlist_id(conn) -> int | None:
    cursor = conn.execute("""
        SELECT pid, json_extract(playlist, '$.trackCount') as trackCount
        FROM web_playlist
        WHERE json_extract(playlist, '$.specialType') = 5
        ORDER BY trackCount DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    return row[0] if row else None
```

### Database Access Pattern
- Copy database to temp location before reading (same pattern as chrome-history)
- Handle database lock when app is running

### Incremental Sync
- Use `updateTime` as cursor for incremental sync
- Store last cursor to avoid re-processing old records

## Success Criteria

1. Successfully read play history from NetEase Cloud Music database
2. Filter out short plays (< 20 seconds)
3. Join with track metadata to get song/artist/album info
4. Mark liked songs with "liked" tag
5. Support incremental sync with cursor
