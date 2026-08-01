"""Channel contracts - re-exported from magi-plugin-sdk."""

from magi_plugin_sdk.channels import (  # noqa: F401
    ChannelConfig,
    ChannelAttachmentStoreProtocol,
    ChannelControlCommandResult,
    ChannelControlPortProtocol,
    ChannelInboundContext,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelSessionMapping,
    ChannelTarget,
    InboundMessage,
    OutboundContent,
)

__all__ = [
    "ChannelConfig",
    "ChannelAttachmentStoreProtocol",
    "ChannelControlCommandResult",
    "ChannelControlPortProtocol",
    "ChannelInboundContext",
    "ChannelInboundRejectedError",
    "ChannelInboundRejectionReason",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelSessionMapping",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
]
