"""Channel abstraction layer — external messaging platform adapters.

Channels provide bidirectional message transport for external platforms
(Telegram, Discord, WeChat, etc.) that plug into the existing chat pipeline
without duplicating any agent logic.
"""

from .base import Channel
from .contracts import (
    ChannelConfig,
    ChannelSessionMapping,
    ChannelTarget,
    InboundMessage,
    OutboundContent,
)
from .registry import ChannelRegistry
from .session_mapper import ChannelSessionMapper

__all__ = [
    "Channel",
    "ChannelConfig",
    "ChannelRegistry",
    "ChannelSessionMapping",
    "ChannelSessionMapper",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
]
