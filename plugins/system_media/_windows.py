"""Windows media reader via SystemMediaTransportControls (SMTC).

Requires the ``winrt-runtime`` and ``winrt-Windows.Media.Control`` packages
(pip install winrt-runtime winrt-Windows.Media.Control), available on
Windows only.
"""
from __future__ import annotations

import logging
from typing import Optional

from .models import MediaState

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    # GlobalSystemMediaTransportControlsSessionPlaybackStatus enum
    5: "playing",   # Playing
    4: "paused",    # Paused
    3: "stopped",   # Stopped
    2: "stopped",   # Closed
    1: "stopped",   # Opened
    0: "stopped",   # Changing
}


async def get_current_media() -> Optional[MediaState]:
    """Return the current media state from Windows SMTC, or *None*."""
    try:
        from winrt.windows.media.control import (  # type: ignore[import-untyped]
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        )
    except ImportError:
        logger.debug("winrt media packages not available")
        return None

    try:
        manager = await SessionManager.request_async()
        session = manager.get_current_session()
        if session is None:
            return None

        # Media properties (IAsyncOperation — directly awaitable in winrt 2.x)
        info = await session.try_get_media_properties_async()

        title = info.title or ""
        artist = info.artist or ""
        album = info.album_title or ""

        # Source app identity -----------------------------------------------
        source_id = session.source_app_user_model_id or ""
        app_name = source_id.split("!")[-1] if "!" in source_id else source_id
        if app_name.lower().endswith(".exe"):
            app_name = app_name[:-4]

        # Playback status ---------------------------------------------------
        pb_info = session.get_playback_info()
        raw_status = int(pb_info.playback_status) if pb_info else 0
        status = _STATUS_MAP.get(raw_status, "stopped")

        return MediaState(
            title=title,
            artist=artist,
            album=album,
            app_name=app_name,
            app_id=source_id,
            playback_status=status,
        )
    except Exception:
        logger.debug("Failed to read SMTC media state", exc_info=True)
        return None
