"""Channel base contracts - re-exported from magi-plugin-sdk."""

from magi_plugin_sdk.channels import (  # noqa: F401
    Channel,
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelSessionMapperProtocol,
)

__all__ = [
    "Channel",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelSessionMapperProtocol",
]
