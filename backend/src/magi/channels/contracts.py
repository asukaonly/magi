"""Channel contracts - re-exported from magi-plugin-sdk."""

from dataclasses import dataclass

from magi_plugin_sdk.channels import (  # noqa: F401
    ChannelConfig,
    ChannelAttachmentStoreProtocol,
    ChannelControlCommandResult,
    ChannelControlPortProtocol,
    ChannelCursorClearProof,
    ChannelInboundClearStrategy,
    ChannelInboundClearRequest,
    ChannelInboundContext,
    ChannelInboundEvidence,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelProviderTimeEvidence,
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
    "ChannelCursorClearProof",
    "ChannelInboundClearStrategy",
    "ChannelInboundClearRequest",
    "ChannelInboundContext",
    "ChannelInboundEvidence",
    "ChannelInboundRejectedError",
    "ChannelInboundRejectionReason",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelProviderTimeEvidence",
    "ChannelSessionMapping",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
]


@dataclass(frozen=True, slots=True)
class ChannelBindingSettings:
    """The settings row (or virtual-default if no row exists yet)."""

    channel_type: str
    external_user_id: str
    auto_approve: bool
    updated_at_ms: int
