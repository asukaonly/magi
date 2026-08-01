"""Channel base contracts - re-exported from magi-plugin-sdk."""

from magi_plugin_sdk.channels import (  # noqa: F401
    Channel,
    ChannelAttachmentStoreProtocol,
    ChannelCursorClearProof,
    ChannelInboundClearStrategy,
    ChannelInboundClearRequest,
    ChannelInboundContext,
    ChannelInboundEvidence,
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelProviderTimeEvidence,
    ChannelSessionMapperProtocol,
)

__all__ = [
    "Channel",
    "ChannelAttachmentStoreProtocol",
    "ChannelCursorClearProof",
    "ChannelInboundClearStrategy",
    "ChannelInboundClearRequest",
    "ChannelInboundContext",
    "ChannelInboundEvidence",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelProviderTimeEvidence",
    "ChannelSessionMapperProtocol",
]
