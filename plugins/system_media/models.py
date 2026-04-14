"""Shared data types for the system-media plugin."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MediaState:
    """Snapshot of the currently playing media from the OS transport controls."""

    title: str = ""
    artist: str = ""
    album: str = ""
    app_name: str = ""
    app_id: str = ""
    playback_status: str = "stopped"  # "playing", "paused", "stopped"

    def is_playing(self) -> bool:
        return self.playback_status == "playing"

    def track_key(self) -> str:
        """Identity key for dedup — same track from same app is one session."""
        return f"{self.app_id}::{self.title}::{self.artist}"
