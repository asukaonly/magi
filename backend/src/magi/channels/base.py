"""Abstract base class for all channel adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import ChannelTarget, OutboundContent


class Channel(ABC):
    """A bidirectional messaging channel connected to an external platform."""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Unique identifier: 'telegram', 'discord', 'wechat', etc."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize platform connection (webhook, polling, etc.)."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shutdown the platform connection."""

    @abstractmethod
    async def send_message(self, target: ChannelTarget, content: OutboundContent) -> None:
        """Deliver a message to an external chat via the platform API."""

    @abstractmethod
    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        """Show typing/processing state on the external platform."""
