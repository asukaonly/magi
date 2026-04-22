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
from .dispatcher import ChannelMessageDispatcher
from .registry import ChannelRegistry
from .session_mapper import ChannelSessionMapper
from magi_plugin_sdk.channels import (
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelSessionMapperProtocol,
)

__all__ = [
    "Channel",
    "ChannelConfig",
    "ChannelMessageDispatcher",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelRegistry",
    "ChannelSessionMapperProtocol",
    "ChannelSessionMapping",
    "ChannelSessionMapper",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
]
