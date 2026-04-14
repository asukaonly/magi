"""Channel lifecycle registry — manages registration, start, and stop."""

from __future__ import annotations

from ..core.logger import get_logger
from .base import Channel

logger = get_logger(__name__)


class ChannelRegistry:
    """Tracks registered channels and manages their lifecycle."""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        ctype = channel.channel_type
        if ctype in self._channels:
            raise ValueError(f"Channel '{ctype}' already registered")
        self._channels[ctype] = channel
        logger.info("Channel registered", channel_type=ctype)

    def get(self, channel_type: str) -> Channel | None:
        return self._channels.get(channel_type)

    def all_channels(self) -> list[Channel]:
        return list(self._channels.values())

    async def start_all(self) -> None:
        for ctype, channel in self._channels.items():
            try:
                await channel.start()
                logger.info("Channel started", channel_type=ctype)
            except Exception:
                logger.exception("Failed to start channel", channel_type=ctype)

    async def stop_all(self) -> None:
        for ctype, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info("Channel stopped", channel_type=ctype)
            except Exception:
                logger.exception("Failed to stop channel", channel_type=ctype)
