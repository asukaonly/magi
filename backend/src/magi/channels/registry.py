"""Channel lifecycle registry — manages registration, start, and stop."""

from __future__ import annotations

from magi_plugin_sdk.channels import ChannelInboundClearStrategy

from ..core.logger import get_logger
from .base import Channel

logger = get_logger(__name__)


class ChannelRegistry:
    """Tracks registered channels and manages their lifecycle."""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}
        self._disabled_channel_types: set[str] = set()

    def register(self, channel: Channel) -> None:
        ctype = channel.channel_type
        if ctype in self._channels:
            raise ValueError(f"Channel '{ctype}' already registered")
        strategy = channel.inbound_clear_strategy
        if not isinstance(strategy, ChannelInboundClearStrategy):
            raise ValueError(
                f"Channel '{ctype}' must declare an inbound clear strategy"
            )
        if (
            strategy is not ChannelInboundClearStrategy.INTERNAL
            and type(channel).inbound_clear_boundary is Channel.inbound_clear_boundary
        ):
            raise ValueError(
                f"External channel '{ctype}' must implement inbound_clear_boundary"
            )
        self._channels[ctype] = channel
        logger.info("Channel registered", channel_type=ctype)

    def get(self, channel_type: str) -> Channel | None:
        if channel_type in self._disabled_channel_types:
            return None
        return self._channels.get(channel_type)

    def all_channels(self) -> list[Channel]:
        return [
            channel
            for channel_type, channel in self._channels.items()
            if channel_type not in self._disabled_channel_types
        ]

    async def start_all(
        self,
        *,
        excluded_channel_types: set[str] | None = None,
    ) -> None:
        excluded = excluded_channel_types or set()
        self._disabled_channel_types = set(excluded)
        for ctype, channel in self._channels.items():
            if ctype in excluded:
                logger.warning(
                    "Channel start skipped after local clear preparation failed",
                    channel_type=ctype,
                )
                continue
            try:
                await channel.start()
                self._disabled_channel_types.discard(ctype)
                logger.info("Channel started", channel_type=ctype)
            except Exception:
                self._disabled_channel_types.add(ctype)
                logger.exception("Failed to start channel", channel_type=ctype)
                try:
                    await channel.stop()
                except Exception:
                    logger.exception(
                        "Failed to stop channel after startup failure",
                        channel_type=ctype,
                    )

    async def stop_all(self) -> None:
        for ctype, channel in self._channels.items():
            if ctype in self._disabled_channel_types:
                continue
            try:
                await channel.stop()
                logger.info("Channel stopped", channel_type=ctype)
            except Exception:
                logger.exception("Failed to stop channel", channel_type=ctype)
