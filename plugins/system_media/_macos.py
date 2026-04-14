"""macOS media reader via AppleScript queries to known media players.

This module queries Spotify and Music.app (the two most common macOS
media sources) through AppleScript.  A future version can be upgraded to
use the private ``MediaRemote.framework`` for truly generic coverage.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Optional

from .models import MediaState

logger = logging.getLogger(__name__)

# AppleScript snippets that return JSON for each known player.
# Each snippet checks if the app is running first to avoid launching it.

_SPOTIFY_SCRIPT = """\
if application "Spotify" is running then
    tell application "Spotify"
        if player state is playing or player state is paused then
            set t to name of current track
            set a to artist of current track
            set al to album of current track
            set s to player state as string
            return "{\\"title\\":\\"" & t & "\\",\\"artist\\":\\"" & a & "\\",\\"album\\":\\"" & al & "\\",\\"status\\":\\"" & s & "\\"}"
        end if
    end tell
end if
return ""
"""

_MUSIC_SCRIPT = """\
if application "Music" is running then
    tell application "Music"
        if player state is playing or player state is paused then
            set t to name of current track
            set a to artist of current track
            set al to album of current track
            set s to player state as string
            return "{\\"title\\":\\"" & t & "\\",\\"artist\\":\\"" & a & "\\",\\"album\\":\\"" & al & "\\",\\"status\\":\\"" & s & "\\"}"
        end if
    end tell
end if
return ""
"""

_PLAYERS: list[tuple[str, str, str]] = [
    # (app_name, app_id, applescript)
    ("Spotify", "com.spotify.client", _SPOTIFY_SCRIPT),
    ("Music", "com.apple.Music", _MUSIC_SCRIPT),
]

_STATUS_MAP = {
    "playing": "playing",
    "paused": "paused",
    "kPSp": "playing",  # Spotify raw enum values
    "kPSP": "paused",
}


async def get_current_media() -> Optional[MediaState]:
    """Return the current media state on macOS, or *None*."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_read)


def _sync_read() -> Optional[MediaState]:
    for app_name, app_id, script in _PLAYERS:
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=3,
            )
            raw = proc.stdout.strip()
            if not raw:
                continue

            data = json.loads(raw)
            title = data.get("title", "")
            if not title:
                continue

            status_raw = data.get("status", "stopped")
            status = _STATUS_MAP.get(status_raw, "stopped")

            return MediaState(
                title=title,
                artist=data.get("artist", ""),
                album=data.get("album", ""),
                app_name=app_name,
                app_id=app_id,
                playback_status=status,
            )
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            continue
        except Exception:
            logger.debug("Failed to query %s via AppleScript", app_name, exc_info=True)
            continue

    return None
