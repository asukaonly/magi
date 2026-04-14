"""Tests for the system-media plugin: state store, sensor, and reader."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from magi.timeline import SensorSyncContext
from magi.utils.runtime import RuntimePaths

from system_media.models import MediaState
from system_media.state import MediaSessionStateStore
from system_media.sensor import SystemMediaTimelineSensor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 4, 14, hour, minute, second, tzinfo=timezone.utc)


def _make_media(
    title: str = "Shape of You",
    artist: str = "Ed Sheeran",
    album: str = "÷",
    app_name: str = "Spotify",
    app_id: str = "spotify.exe",
    status: str = "playing",
) -> MediaState:
    return MediaState(
        title=title,
        artist=artist,
        album=album,
        app_name=app_name,
        app_id=app_id,
        playback_status=status,
    )


def _ctx(tmp_path: Path) -> SensorSyncContext:
    return SensorSyncContext(
        source_type="system_media",
        manual=False,
        last_cursor=None,
        last_success_at=None,
        limit=100,
        runtime_paths=RuntimePaths(base_dir=tmp_path / ".magi"),
        plugin_settings={},
    )


# ===================================================================
# MediaState model tests
# ===================================================================

class TestMediaState:

    def test_is_playing(self) -> None:
        assert _make_media(status="playing").is_playing()
        assert not _make_media(status="paused").is_playing()
        assert not _make_media(status="stopped").is_playing()

    def test_track_key_contains_app_title_artist(self) -> None:
        m = _make_media(title="Hello", artist="Adele", app_id="spotify.exe")
        assert m.track_key() == "spotify.exe::Hello::Adele"

    def test_track_key_different_apps_are_different(self) -> None:
        a = _make_media(app_id="spotify.exe")
        b = _make_media(app_id="chrome.exe")
        assert a.track_key() != b.track_key()


# ===================================================================
# StateStore tests
# ===================================================================

class TestMediaSessionStateStore:

    def test_single_track_creates_session(self, tmp_path: Path) -> None:
        """Playing the same track across several polls creates one session."""
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")
        media = _make_media()

        for i in range(5):
            asyncio.run(store.apply_poll(runtime_paths=rp, media=media, now=_dt(10, i * 5)))

        # Session is still in progress — nothing flushed yet
        completed = asyncio.run(store.flush_completed(runtime_paths=rp))
        assert completed == []

    def test_track_change_closes_session(self, tmp_path: Path) -> None:
        store = MediaSessionStateStore(pause_timeout_s=300, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        # Play track A for 2 minutes
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="Track A"), now=_dt(10, 0)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="Track A"), now=_dt(10, 2)))

        # Switch to track B
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="Track B"), now=_dt(10, 3)))

        completed = asyncio.run(store.flush_completed(runtime_paths=rp))
        assert len(completed) == 1
        assert completed[0]["title"] == "Track A"
        assert completed[0]["duration_seconds"] == 180  # 10:00 to 10:03

    def test_pause_timeout_closes_session(self, tmp_path: Path) -> None:
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        # Play for a bit
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(), now=_dt(10, 0)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(), now=_dt(10, 1)))

        # Pause (media=None)
        asyncio.run(store.apply_poll(runtime_paths=rp, media=None, now=_dt(10, 1, 30)))

        # Not timed out yet (30s < 60s)
        completed = asyncio.run(store.flush_completed(runtime_paths=rp))
        assert completed == []

        # Now exceed timeout
        asyncio.run(store.apply_poll(runtime_paths=rp, media=None, now=_dt(10, 3)))

        completed = asyncio.run(store.flush_completed(runtime_paths=rp))
        assert len(completed) == 1
        assert completed[0]["duration_seconds"] == 60  # last_seen was at 10:01

    def test_short_session_discarded(self, tmp_path: Path) -> None:
        """Sessions shorter than min_session_s are dropped."""
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=30)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        # Play for just 10 seconds, then switch
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="Short"), now=_dt(10, 0, 0)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="Short"), now=_dt(10, 0, 10)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="Long"), now=_dt(10, 0, 15)))

        completed = asyncio.run(store.flush_completed(runtime_paths=rp))
        # "Short" session was only 10s, under the 30s minimum
        assert all(s["title"] != "Short" for s in completed)

    def test_multiple_sessions_flushed_in_order(self, tmp_path: Path) -> None:
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="A"), now=_dt(10, 0)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="A"), now=_dt(10, 2)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="B"), now=_dt(10, 3)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="B"), now=_dt(10, 5)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="C"), now=_dt(10, 6)))

        completed = asyncio.run(store.flush_completed(runtime_paths=rp))
        assert len(completed) == 2
        assert completed[0]["title"] == "A"
        assert completed[1]["title"] == "B"

    def test_flush_clears_completed(self, tmp_path: Path) -> None:
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="A"), now=_dt(10, 0)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="A"), now=_dt(10, 2)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="B"), now=_dt(10, 3)))

        first = asyncio.run(store.flush_completed(runtime_paths=rp))
        assert len(first) == 1

        second = asyncio.run(store.flush_completed(runtime_paths=rp))
        assert second == []

    def test_paused_media_does_not_start_session(self, tmp_path: Path) -> None:
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        asyncio.run(store.apply_poll(
            runtime_paths=rp,
            media=_make_media(status="paused"),
            now=_dt(10, 0),
        ))

        info = asyncio.run(store.flush_in_progress(runtime_paths=rp, now=_dt(10, 1)))
        assert info["current_track"] is None

    def test_empty_title_ignored(self, tmp_path: Path) -> None:
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        asyncio.run(store.apply_poll(
            runtime_paths=rp,
            media=_make_media(title=""),
            now=_dt(10, 0),
        ))

        info = asyncio.run(store.flush_in_progress(runtime_paths=rp, now=_dt(10, 1)))
        assert info["current_track"] is None

    def test_flush_in_progress_reports_current(self, tmp_path: Path) -> None:
        store = MediaSessionStateStore(pause_timeout_s=300, min_session_s=10)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="Now"), now=_dt(10, 0)))

        info = asyncio.run(store.flush_in_progress(runtime_paths=rp, now=_dt(10, 1)))
        assert info["current_track"] == "Now"
        assert info["current_app"] == "Spotify"
        assert info["pending_sessions"] == 0

    def test_state_survives_reload(self, tmp_path: Path) -> None:
        """State is persisted to disk and survives re-instantiation."""
        rp = RuntimePaths(base_dir=tmp_path / ".magi")

        store1 = MediaSessionStateStore(pause_timeout_s=300, min_session_s=10)
        asyncio.run(store1.apply_poll(runtime_paths=rp, media=_make_media(title="X"), now=_dt(10, 0)))
        asyncio.run(store1.apply_poll(runtime_paths=rp, media=_make_media(title="X"), now=_dt(10, 2)))

        # New store instance, same path
        store2 = MediaSessionStateStore(pause_timeout_s=300, min_session_s=10)
        asyncio.run(store2.apply_poll(runtime_paths=rp, media=_make_media(title="Y"), now=_dt(10, 3)))

        completed = asyncio.run(store2.flush_completed(runtime_paths=rp))
        assert len(completed) == 1
        assert completed[0]["title"] == "X"
        assert completed[0]["duration_seconds"] == 180  # 10:00 to 10:03


# ===================================================================
# Sensor tests
# ===================================================================

class TestSystemMediaTimelineSensor:

    def test_collect_items_polls_and_flushes(self, tmp_path: Path) -> None:
        """Sensor polls media, feeds state store, and returns completed sessions."""
        store = MediaSessionStateStore(pause_timeout_s=60, min_session_s=10)
        sensor = SystemMediaTimelineSensor(state_store=store)
        rp = RuntimePaths(base_dir=tmp_path / ".magi")
        ctx = _ctx(tmp_path)

        # Pre-populate state: play track A, then switch to B
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="A"), now=_dt(10, 0)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="A"), now=_dt(10, 2)))
        asyncio.run(store.apply_poll(runtime_paths=rp, media=_make_media(title="B"), now=_dt(10, 3)))

        # Sensor collect should return track A as completed (B is mocked as current)
        mock_media = _make_media(title="B")
        with patch("system_media.sensor.get_current_media", new_callable=AsyncMock, return_value=mock_media):
            with patch.object(sensor, "_now", return_value=_dt(10, 4)):
                result = asyncio.run(sensor.collect_items(ctx))

        assert len(result.items) == 1
        assert result.items[0]["title"] == "A"

    def test_collect_items_handles_no_media(self, tmp_path: Path) -> None:
        """No media playing returns empty items."""
        sensor = SystemMediaTimelineSensor()
        ctx = _ctx(tmp_path)

        with patch("system_media.sensor.get_current_media", new_callable=AsyncMock, return_value=None):
            with patch.object(sensor, "_now", return_value=_dt(10, 0)):
                result = asyncio.run(sensor.collect_items(ctx))

        assert result.items == []

    def test_build_output_with_artist(self, tmp_path: Path) -> None:
        sensor = SystemMediaTimelineSensor()
        item = {
            "title": "Shape of You",
            "artist": "Ed Sheeran",
            "album": "÷",
            "app_name": "Spotify",
            "app_id": "spotify.exe",
            "started_at": _dt(10, 0).isoformat(),
            "ended_at": _dt(10, 4).isoformat(),
            "duration_seconds": 240,
        }
        output = asyncio.run(sensor.build_output(item))
        assert "Shape of You" in output.title
        assert "Ed Sheeran" in output.title
        assert "4m" in output.title
        assert "Spotify" in output.summary
        assert output.tags == ["media", "music", "listening"]

    def test_build_output_without_artist(self, tmp_path: Path) -> None:
        sensor = SystemMediaTimelineSensor()
        item = {
            "title": "Podcast Episode 42",
            "artist": "",
            "album": "",
            "app_name": "chrome",
            "app_id": "chrome.exe",
            "started_at": _dt(14, 0).isoformat(),
            "ended_at": _dt(14, 30).isoformat(),
            "duration_seconds": 1800,
        }
        output = asyncio.run(sensor.build_output(item))
        assert "Podcast Episode 42" in output.title
        assert "30m" in output.title
        assert "Ed Sheeran" not in output.title  # no artist in title

    def test_source_item_identity_uniqueness(self) -> None:
        sensor = SystemMediaTimelineSensor()
        item_a = {"started_at": "2026-04-14T10:00:00", "app_id": "spotify", "title": "X"}
        item_b = {"started_at": "2026-04-14T10:00:00", "app_id": "spotify", "title": "Y"}
        assert sensor.source_item_identity(item_a) != sensor.source_item_identity(item_b)

    def test_version_fingerprint_changes_with_duration(self) -> None:
        sensor = SystemMediaTimelineSensor()
        item = {"started_at": "2026-04-14T10:00:00", "app_id": "sp", "title": "T", "duration_seconds": 100}
        fp1 = sensor.source_item_version_fingerprint(item)
        item["duration_seconds"] = 200
        fp2 = sensor.source_item_version_fingerprint(item)
        assert fp1 != fp2
