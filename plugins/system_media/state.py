"""State store for media playback session aggregation.

Tracks the currently playing track and aggregates continuous playback
into *listening sessions*.  A session is closed (and ready to flush) when
the track changes, playback stops, or the pause exceeds a timeout.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import MediaState

logger = logging.getLogger(__name__)

# Default: pause longer than 5 minutes closes a session.
DEFAULT_PAUSE_TIMEOUT_S = 300
# Sessions shorter than this are discarded as noise.
DEFAULT_MIN_SESSION_S = 30


class MediaSessionStateStore:
    """Persist and manage in-flight listening sessions."""

    _locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        *,
        pause_timeout_s: int = DEFAULT_PAUSE_TIMEOUT_S,
        min_session_s: int = DEFAULT_MIN_SESSION_S,
    ) -> None:
        self._pause_timeout_s = pause_timeout_s
        self._min_session_s = min_session_s

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _state_path(self, runtime_paths: Any) -> Path:
        return runtime_paths.plugin_cache_dir("system_media") / "state.json"

    def _lock_for(self, path: Path) -> asyncio.Lock:
        key = str(path.resolve())
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"current_session": None, "completed": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"current_session": None, "completed": []}

    def _save(self, path: Path, state: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=True, sort_keys=True), encoding="utf-8")

    # ------------------------------------------------------------------
    # Core state machine
    # ------------------------------------------------------------------

    async def apply_poll(
        self,
        *,
        runtime_paths: Any,
        media: MediaState | None,
        now: datetime,
    ) -> None:
        """Process one poll result and update session state."""
        path = self._state_path(runtime_paths)
        async with self._lock_for(path):
            state = self._load(path)
            current = state.get("current_session")
            completed: list[dict[str, Any]] = list(state.get("completed") or [])

            if media is not None and media.is_playing() and media.title:
                track_key = media.track_key()
                now_iso = now.isoformat()

                if current is not None and current.get("track_key") == track_key:
                    # Same track still playing — extend session
                    current["last_seen_at"] = now_iso
                else:
                    # Track changed — close previous session (if any)
                    if current is not None:
                        self._close_session(current, now_iso, completed)

                    # Start new session
                    current = {
                        "track_key": track_key,
                        "title": media.title,
                        "artist": media.artist,
                        "album": media.album,
                        "app_name": media.app_name,
                        "app_id": media.app_id,
                        "started_at": now_iso,
                        "last_seen_at": now_iso,
                    }
            elif current is not None:
                # Nothing playing (or paused) — check pause timeout
                last_seen = datetime.fromisoformat(current["last_seen_at"])
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                elapsed = (now - last_seen).total_seconds()
                if elapsed >= self._pause_timeout_s:
                    self._close_session(current, current["last_seen_at"], completed)
                    current = None

            self._save(path, {"current_session": current, "completed": completed})

    def _close_session(
        self,
        session: dict[str, Any],
        end_time_iso: str,
        completed: list[dict[str, Any]],
    ) -> None:
        started = datetime.fromisoformat(session["started_at"])
        ended = datetime.fromisoformat(end_time_iso)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)

        duration = max(0, int((ended - started).total_seconds()))
        if duration >= self._min_session_s:
            completed.append({
                "title": session["title"],
                "artist": session["artist"],
                "album": session["album"],
                "app_name": session["app_name"],
                "app_id": session["app_id"],
                "started_at": session["started_at"],
                "ended_at": end_time_iso,
                "duration_seconds": duration,
            })

    # ------------------------------------------------------------------
    # Flush API (called by sensor)
    # ------------------------------------------------------------------

    async def flush_completed(
        self,
        *,
        runtime_paths: Any,
    ) -> list[dict[str, Any]]:
        """Return and clear all completed sessions."""
        path = self._state_path(runtime_paths)
        async with self._lock_for(path):
            state = self._load(path)
            completed = list(state.get("completed") or [])
            state["completed"] = []
            self._save(path, state)
        return completed

    async def flush_in_progress(
        self,
        *,
        runtime_paths: Any,
        now: datetime,
    ) -> dict[str, Any]:
        """Return diagnostic info about in-flight state."""
        path = self._state_path(runtime_paths)
        async with self._lock_for(path):
            state = self._load(path)
            current = state.get("current_session")
            pending = len(state.get("completed") or [])

        return {
            "current_track": current.get("title") if current else None,
            "current_app": current.get("app_name") if current else None,
            "pending_sessions": pending,
            "checked_at": now.isoformat(),
        }
