from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add plugins directory to sys.path to import plugins
_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from netease_music.normalizers import (
    build_netease_url,
    extract_track_info,
    parse_track_json,
)
from netease_music.reader import NeteaseMusicReader, DEFAULT_DB_PATH


def test_parse_track_json_valid_json() -> None:
    """Test parsing valid JSON string."""
    json_str = '{"id": "123", "name": "Test Song", "duration": 180000, "artists": [{"id": "456", "name": "Test Artist"}], "album": {"id": "789", "name": "Test Album", "picUrl": "http://example.com/cover.jpg"}}'
    result = parse_track_json(json_str)
    assert result == {
        "id": "123",
        "name": "Test Song",
        "duration": 180000,
        "artists": [{"id": "456", "name": "Test Artist"}],
        "album": {"id": "789", "name": "Test Album", "picUrl": "http://example.com/cover.jpg"}
    }


def test_parse_track_json_empty_string() -> None:
    """Test parsing empty string."""
    result = parse_track_json("")
    assert result == {}


def test_parse_track_json_none() -> None:
    """Test parsing None."""
    result = parse_track_json(None)
    assert result == {}


def test_parse_track_json_invalid_json() -> None:
    """Test parsing invalid JSON string."""
    result = parse_track_json("invalid json string")
    assert result == {}


def test_extract_track_info_full_info() -> None:
    """Test extracting track info with full data."""
    track_data = {
        "id": "123",
        "name": "Test Song",
        "duration": 180000,
        "artists": [{"id": "456", "name": "Test Artist"}],
        "album": {"id": "789", "name": "Test Album", "picUrl": "http://example.com/cover.jpg"}
    }
    result = extract_track_info(track_data)
    assert result == {
        "track_id": "123",
        "track_name": "Test Song",
        "track_duration_ms": 180000,
        "artist_id": "456",
        "artist_name": "Test Artist",
        "album_id": "789",
        "album_name": "Test Album",
        "album_cover_url": "http://example.com/cover.jpg"
    }


def test_extract_track_info_missing_artists() -> None:
    """Test extracting track info with missing artists."""
    track_data = {
        "id": "123",
        "name": "Test Song",
        "duration": 180000,
        "artists": [],
        "album": {"id": "789", "name": "Test Album"}
    }
    result = extract_track_info(track_data)
    assert result == {
        "track_id": "123",
        "track_name": "Test Song",
        "track_duration_ms": 180000,
        "artist_id": None,
        "artist_name": None,
        "album_id": "789",
        "album_name": "Test Album",
        "album_cover_url": None
    }


def test_extract_track_info_missing_album() -> None:
    """Test extracting track info with missing album."""
    track_data = {
        "id": "123",
        "name": "Test Song",
        "duration": 180000,
        "artists": [{"id": "456", "name": "Test Artist"}],
        "album": None
    }
    result = extract_track_info(track_data)
    assert result == {
        "track_id": "123",
        "track_name": "Test Song",
        "track_duration_ms": 180000,
        "artist_id": "456",
        "artist_name": "Test Artist",
        "album_id": None,
        "album_name": None,
        "album_cover_url": None
    }


def test_extract_track_info_no_artists_album() -> None:
    """Test extracting track info with neither artists nor album."""
    track_data = {
        "id": "123",
        "name": "Test Song",
        "duration": 180000
    }
    result = extract_track_info(track_data)
    assert result == {
        "track_id": "123",
        "track_name": "Test Song",
        "track_duration_ms": 180000,
        "artist_id": None,
        "artist_name": None,
        "album_id": None,
        "album_name": None,
        "album_cover_url": None
    }


def test_build_netease_url_basic() -> None:
    """Test basic NetEase URL construction."""
    track_id = "123456"
    result = build_netease_url(track_id)
    assert result == "https://music.163.com/#/song?id=123456"


def test_build_netease_url_numeric_id() -> None:
    """Test NetEase URL construction with numeric string ID."""
    track_id = "123"
    result = build_netease_url(track_id)
    assert result == "https://music.163.com/#/song?id=123"


def test_build_netease_url_long_id() -> None:
    """Test NetEase URL construction with long ID."""
    track_id = "876543210987654321"
    result = build_netease_url(track_id)
    assert result == "https://music.163.com/#/song?id=876543210987654321"


# Tests for NeteaseMusicReader
import sqlite3
import tempfile
from datetime import datetime

# Tests for NeteaseMusicTimelineSensor
from unittest.mock import AsyncMock, MagicMock, patch

# Import after adding plugins to path
from netease_music.reader import NeteaseMusicReader, DEFAULT_DB_PATH
from netease_music.sensor import NeteaseMusicTimelineSensor


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database file path."""
    return tmp_path / "test.db"


@pytest.fixture
def sample_database(temp_db_path):
    """Create a sample database with test data."""
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS playingCount (
        resourceId TEXT PRIMARY KEY,
        playDuration INTEGER,
        updateTime INTEGER,
        source TEXT,
        uid TEXT,
        resourceType TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historyTracks (
        id TEXT PRIMARY KEY,
        playtime INTEGER,
        jsonStr TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS web_playlist (
        pid INTEGER PRIMARY KEY,
        playlist TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS web_playlist_track (
        pid INTEGER,
        tid TEXT,
        PRIMARY KEY (pid, tid)
    )
    """)

    # Insert test data
    # Play records with different durations
    cursor.execute("""
    INSERT INTO playingCount (resourceId, playDuration, updateTime, source, uid, resourceType)
    VALUES
        ('track1', 30, 1641000000, 'local', 'user1', 'track'),
        ('track2', 15, 1641001000, 'local', 'user1', 'track'),
        ('track3', 45, 1641002000, 'local', 'user1', 'track'),
        ('track4', 25, 1641003000, 'local', 'user1', 'track')
    """)

    # Track metadata
    cursor.execute("""
    INSERT INTO historyTracks (id, playtime, jsonStr)
    VALUES
        ('track1', 1641000000, '{"id": "track1", "name": "Song 1", "duration": 180000, "artists": [{"id": "artist1", "name": "Artist 1"}], "album": {"id": "album1", "name": "Album 1"}}'),
        ('track3', 1641002000, '{"id": "track3", "name": "Song 3", "duration": 200000, "artists": [{"id": "artist3", "name": "Artist 3"}], "album": {"id": "album3", "name": "Album 3"}}'),
        ('track4', 1641003000, '{"id": "track4", "name": "Song 4", "duration": 190000, "artists": [{"id": "artist4", "name": "Artist 4"}], "album": {"id": "album4", "name": "Album 4"}}')
    """)

    # Liked playlist
    cursor.execute("""
    INSERT INTO web_playlist (pid, playlist)
    VALUES (5, '{"name": "我喜欢", "specialType": 5}')
    """)

    # Liked tracks
    cursor.execute("""
    INSERT INTO web_playlist_track (pid, tid)
    VALUES (5, 'track1'), (5, 'track4')
    """)

    conn.commit()
    conn.close()
    return temp_db_path


def test_resolve_db_path(sample_database):
    """Test database path resolution."""
    reader = NeteaseMusicReader()
    resolved_path = reader.resolve_db_path(str(sample_database))
    assert resolved_path == Path(sample_database)


def test_get_liked_playlist_id(sample_database):
    """Test finding the liked songs playlist ID."""
    reader = NeteaseMusicReader()

    # Create a copy of the database to test with
    temp_db_path = reader._copy_database(str(sample_database))
    conn = sqlite3.connect(temp_db_path)
    playlist_id = reader.get_liked_playlist_id(conn)
    conn.close()

    # Clean up temp file
    try:
        temp_db_path.unlink()
    except OSError:
        pass

    assert playlist_id == 5


def test_get_liked_track_ids(sample_database):
    """Test getting liked track IDs from a playlist."""
    reader = NeteaseMusicReader()
    conn = sqlite3.connect(sample_database)
    liked_ids = reader.get_liked_track_ids(conn, 5)
    conn.close()

    assert liked_ids == {'track1', 'track4'}


def test_read_play_records_filters_duration(sample_database):
    """Test that play records are filtered by minimum duration."""
    reader = NeteaseMusicReader()
    records = reader.read_play_records(
        source_path=str(sample_database),
        min_play_duration=20,
        limit=10
    )

    # Only tracks with duration >= 20 should be included
    track_ids = [r['track_id'] for r in records]
    assert len(records) == 3  # track1 (30s), track3 (45s), track4 (25s)
    assert 'track1' in track_ids
    assert 'track3' in track_ids
    assert 'track4' in track_ids
    assert 'track2' not in track_ids  # Only 15s duration


def test_read_play_records_includes_track_info(sample_database):
    """Test that track information is included in play records."""
    reader = NeteaseMusicReader()
    records = reader.read_play_records(
        source_path=str(sample_database),
        min_play_duration=0,
        limit=10
    )

    assert len(records) > 0
    first_record = records[0]
    assert 'track_name' in first_record
    assert 'artist_name' in first_record
    assert 'album_name' in first_record
    assert 'track_duration_ms' in first_record


def test_read_play_records_marks_liked(sample_database):
    """Test that liked tracks are marked correctly."""
    reader = NeteaseMusicReader()
    records = reader.read_play_records(
        source_path=str(sample_database),
        min_play_duration=0,
        limit=10
    )

    # Check is_liked flag
    for record in records:
        if record['track_id'] == 'track1' or record['track_id'] == 'track4':
            assert record['is_liked'] is True
        else:
            assert record['is_liked'] is False


def test_read_play_records_with_cursor(sample_database):
    """Test reading play records with cursor pagination."""
    reader = NeteaseMusicReader()
    records = reader.read_play_records(
        source_path=str(sample_database),
        min_play_duration=0,
        limit=2
    )

    # Should return only 2 records
    assert len(records) == 2

    # Records should be sorted by updateTime
    assert records[0]['update_time'] < records[1]['update_time']


# Tests for NeteaseMusicTimelineSensor
def test_sensor_id():
    """Test sensor ID."""
    sensor = NeteaseMusicTimelineSensor()
    assert sensor.sensor_id == "timeline.netease_music"
    assert sensor.display_name == "NetEase Cloud Music"
    assert sensor.source_type == "netease_music"
    assert sensor.polling_mode == "interval"
    assert sensor.default_interval == 30
    assert sensor.update_key_fields == ("track_id", "update_time")
    assert sensor.relation_edge_whitelist == ("LISTENED",)
    assert sensor.supports_pull_sync is True


def test_source_item_identity():
    """Test source item identity generation."""
    sensor = NeteaseMusicTimelineSensor()
    item = {
        "track_id": "123",
        "update_time": 1641000000,
        "track_name": "Test Song"
    }
    identity = sensor.source_item_identity(item)
    assert identity == "netease_123_1641000000"


def test_source_item_version_fingerprint():
    """Test source item version fingerprint generation."""
    sensor = NeteaseMusicTimelineSensor()
    item = {
        "resource_id": "123",
        "update_time": 1641000000,
        "play_duration_sec": 30
    }
    fingerprint = sensor.source_item_version_fingerprint(item)
    # Should be consistent for same data
    assert fingerprint == sensor.source_item_version_fingerprint(item)
    # Should change with different data
    different_item = {
        "resource_id": "123",
        "update_time": 1641000000,
        "play_duration_sec": 45
    }
    assert fingerprint != sensor.source_item_version_fingerprint(different_item)


@pytest.mark.asyncio
async def test_collect_items_returns_records():
    """Test that collect_items returns records from reader."""
    sensor = NeteaseMusicTimelineSensor(min_play_duration=20)

    # Mock the reader
    mock_reader = AsyncMock(spec=NeteaseMusicReader)
    mock_reader.read_play_records.return_value = [
        {
            "track_id": "123",
            "track_name": "Test Song",
            "artist_name": "Test Artist",
            "album_name": "Test Album",
            "play_duration_sec": 30,
            "update_time": 1641000000,
            "source": "local",
            "is_liked": True,
            "track_duration_ms": 180000
        }
    ]
    sensor._reader = mock_reader

    # Mock context
    mock_context = MagicMock()
    mock_context.plugin_settings = {"sensors": {"netease_music": {}}}
    mock_context.last_cursor = None
    mock_context.last_success_at = None
    mock_context.limit = 100

    # Call collect_items
    result = await sensor.collect_items(mock_context)

    # Verify result
    assert len(result.items) == 1
    assert result.items[0]["track_id"] == "123"
    assert result.next_cursor is None

    # Verify reader was called with correct parameters
    mock_reader.read_play_records.assert_called_once_with(
        source_path=DEFAULT_DB_PATH,
        min_play_duration=20,
        limit=100,
        last_cursor=None
    )


@pytest.mark.asyncio
async def test_build_output():
    """Test building sensor output from item."""
    sensor = NeteaseMusicTimelineSensor()

    item = {
        "track_id": "123",
        "track_name": "Test Song",
        "artist_name": "Test Artist",
        "album_name": "Test Album",
        "play_duration_sec": 30,
        "update_time": 1641000000,
        "source": "local",
        "is_liked": True,
        "track_duration_ms": 180000
    }

    output = await sensor.build_output(item)

    # Check output properties
    assert output.source_type == "netease_music"
    assert output.source_item_id == "netease_123_1641000000"
    assert output.title == "Test Song - Test Artist"
    assert output.summary == "播放了 Test Song (30秒)"
    assert output.occurred_at == 1641000000

    # Check content blocks
    assert len(output.content_blocks) == 3
    assert output.content_blocks[0].kind == "text"
    assert output.content_blocks[0].value == "Test Song"
    assert output.content_blocks[1].kind == "text"
    assert output.content_blocks[1].value == "Test Artist"
    assert output.content_blocks[2].kind == "text"
    assert output.content_blocks[2].value == "Test Album"

    # Check tags
    assert set(output.tags) == {"netease_music", "music", "listening", "liked"}

    # Check provenance
    provenance = output.provenance
    assert provenance["sensor_id"] == "timeline.netease_music"
    assert provenance["platform"] == "netease_music"
    assert provenance["track_id"] == "123"
    assert provenance["track_name"] == "Test Song"
    assert provenance["track_duration_ms"] == 180000
    assert provenance["artist_id"] is None  # Not in the item
    assert provenance["artist_name"] == "Test Artist"
    assert provenance["album_id"] is None  # Not in the item
    assert provenance["album_name"] == "Test Album"
    assert provenance["play_source"] == "local"
    assert provenance["play_duration_sec"] == 30
    assert "netease_url" in provenance
    assert provenance["is_liked"] is True


@pytest.mark.asyncio
async def test_build_output_marks_liked():
    """Test building sensor output marks liked tracks correctly."""
    sensor = NeteaseMusicTimelineSensor()

    liked_item = {
        "track_id": "123",
        "track_name": "Liked Song",
        "artist_name": "Artist",
        "album_name": "Album",
        "play_duration_sec": 30,
        "update_time": 1641000000,
        "source": "local",
        "is_liked": True
    }

    not_liked_item = {
        "track_id": "456",
        "track_name": "Not Liked Song",
        "artist_name": "Artist",
        "album_name": "Album",
        "play_duration_sec": 30,
        "update_time": 1641000001,
        "source": "local",
        "is_liked": False
    }

    liked_output = await sensor.build_output(liked_item)
    not_liked_output = await sensor.build_output(not_liked_item)

    assert "liked" in liked_output.tags
    assert "liked" not in not_liked_output.tags


# Tests for NeteaseMusicPlugin
import sys
from pathlib import Path

# Add plugins directory to sys.path to import plugin
_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from magi.config.models import AppConfig, PluginSettings
from magi.plugins.actions import ActionRegistry
from magi.plugins.manager import PluginManager
from magi.plugins.sensors import SensorRegistry
from magi.timeline import SensorSyncContext
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths
from netease_music.plugin import NeteaseMusicPlugin, DEFAULT_SETTINGS


def test_default_settings():
    """Test that default settings are correctly defined."""
    assert isinstance(DEFAULT_SETTINGS, dict)
    assert "enabled" in DEFAULT_SETTINGS
    assert "sync_mode" in DEFAULT_SETTINGS
    assert "sync_interval_minutes" in DEFAULT_SETTINGS
    assert "min_play_duration" in DEFAULT_SETTINGS
    assert "db_path" in DEFAULT_SETTINGS
    assert "default_retention_mode" in DEFAULT_SETTINGS
    assert "storage_mode" in DEFAULT_SETTINGS
    assert "initial_sync_policy" in DEFAULT_SETTINGS

    # Check default values
    assert DEFAULT_SETTINGS["enabled"] is False
    assert DEFAULT_SETTINGS["sync_mode"] == "manual"
    assert DEFAULT_SETTINGS["sync_interval_minutes"] == 30
    assert DEFAULT_SETTINGS["min_play_duration"] == 20
    assert DEFAULT_SETTINGS["default_retention_mode"] == "analyze_only"
    assert DEFAULT_SETTINGS["storage_mode"] == "managed"
    assert DEFAULT_SETTINGS["initial_sync_policy"] == "from_now"


def test_plugin_get_sensors():
    """Test that NeteaseMusicPlugin returns correct sensor specification."""
    plugin = NeteaseMusicPlugin()

    sensors = plugin.get_sensors()

    # Should return one sensor
    assert len(sensors) == 1

    # Check sensor details
    sensor_id, sensor_instance, sensor_spec = sensors[0]
    assert sensor_id == "timeline.netease_music"
    assert isinstance(sensor_instance, NeteaseMusicTimelineSensor)
    assert sensor_spec.sensor_id == "timeline.netease_music"
    assert sensor_spec.display_name == "NetEase Cloud Music"
    assert sensor_spec.description == "Local NetEase Cloud Music play history ingestion for the timeline."
    assert sensor_spec.domain == "timeline"
    assert sensor_spec.surface == "timeline"
    assert "default_settings" in sensor_spec.metadata
    assert sensor_spec.metadata["default_settings"] == DEFAULT_SETTINGS


def test_plugin_get_sensors_with_settings():
    """Test that NeteaseMusicPlugin correctly applies settings from configuration."""
    plugin = NeteaseMusicPlugin()

    # Test with custom settings
    test_settings = {
        "sensors": {
            "netease_music": {
                "enabled": True,
                "sync_mode": "interval",
                "sync_interval_minutes": 60,
                "min_play_duration": 30,
                "db_path": "/custom/path.db",
                "default_retention_mode": "full",
                "storage_mode": "local",
                "initial_sync_policy": "full"
            }
        }
    }
    plugin.settings = test_settings

    sensors = plugin.get_sensors()
    sensor_id, sensor_instance, sensor_spec = sensors[0]

    # Check that settings were applied
    assert sensor_spec.sync_mode == "interval"

    # The sensor instance should have been created with custom settings
    assert sensor_instance.min_play_duration == 30
