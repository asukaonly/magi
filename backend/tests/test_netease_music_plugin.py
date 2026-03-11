from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add parent directory to sys.path to import plugins
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from plugins.netease_music.normalizers import (
    build_netease_url,
    extract_track_info,
    parse_track_json,
)


def test_parse_track_json_valid_json() -> None:
    """Test parsing valid JSON string."""
    json_str = '{"id": "123", "name": "Test Song", "duration": 180000, "ar": [{"id": "456", "name": "Test Artist"}], "al": {"id": "789", "name": "Test Album", "picUrl": "http://example.com/cover.jpg"}}'
    result = parse_track_json(json_str)
    assert result == {
        "id": "123",
        "name": "Test Song",
        "duration": 180000,
        "ar": [{"id": "456", "name": "Test Artist"}],
        "al": {"id": "789", "name": "Test Album", "picUrl": "http://example.com/cover.jpg"}
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
        "ar": [{"id": "456", "name": "Test Artist"}],
        "al": {"id": "789", "name": "Test Album", "picUrl": "http://example.com/cover.jpg"}
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
        "ar": [],
        "al": {"id": "789", "name": "Test Album"}
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
        "ar": [{"id": "456", "name": "Test Artist"}],
        "al": None
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