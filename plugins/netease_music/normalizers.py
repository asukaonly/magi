from __future__ import annotations

import json
from typing import Any


def parse_track_json(json_str: str | None) -> dict[str, Any]:
    """Parse track JSON string into a dictionary."""
    if json_str is None or json_str.strip() == "":
        return {}

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}


def extract_track_info(track_data: dict[str, Any]) -> dict[str, Any]:
    """Extract normalized track info from parsed JSON."""
    result = {
        "track_id": track_data.get("id"),
        "track_name": track_data.get("name"),
        "track_duration_ms": track_data.get("duration"),
        "artist_id": None,
        "artist_name": None,
        "album_id": None,
        "album_name": None,
        "album_cover_url": None,
    }

    # Extract artist info
    artists = track_data.get("ar", [])
    if artists and len(artists) > 0:
        result["artist_id"] = artists[0].get("id")
        result["artist_name"] = artists[0].get("name")

    # Extract album info
    album = track_data.get("al")
    if album:
        result["album_id"] = album.get("id")
        result["album_name"] = album.get("name")
        result["album_cover_url"] = album.get("picUrl")

    return result


def build_netease_url(track_id: str) -> str:
    """Build NetEase Cloud Music URL for a track."""
    return f"https://music.163.com/#/song?id={track_id}"