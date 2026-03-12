from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add plugins directory to sys.path to import plugins
_plugins_path = Path(__file__).resolve().parents[2] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from netease_music.normalizers import (
    build_netease_url,
    extract_track_info,
    parse_track_json,
)
from netease_music.reader import NeteaseMusicReader


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