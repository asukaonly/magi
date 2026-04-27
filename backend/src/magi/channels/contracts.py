"""Channel contracts - re-exported from magi-plugin-sdk."""

from magi_plugin_sdk.channels import (  # noqa: F401
    ChannelConfig,
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelSessionMapping,
    ChannelTarget,
    InboundMessage,
    OutboundContent,
)

__all__ = [
    "ChannelConfig",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelSessionMapping",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
]
