from __future__ import annotations

from magi.channels import Channel as BackendChannel
from magi.channels import ChannelConfig as BackendChannelConfig
from magi.channels import ChannelAttachmentStoreProtocol as BackendChannelAttachmentStoreProtocol
from magi.channels import ChannelCursorClearProof as BackendChannelCursorClearProof
from magi.channels import ChannelInboundClearRequest as BackendChannelInboundClearRequest
from magi.channels import ChannelInboundClearStrategy as BackendChannelInboundClearStrategy
from magi.channels import ChannelInboundContext as BackendChannelInboundContext
from magi.channels import ChannelInboundRejectedError as BackendChannelInboundRejectedError
from magi.channels import ChannelInboundRejectionReason as BackendChannelInboundRejectionReason
from magi.channels import ChannelMessageDispatcherProtocol as BackendChannelMessageDispatcherProtocol
from magi.channels import ChannelMessageDispatchOutcome as BackendChannelMessageDispatchOutcome
from magi.channels import ChannelProviderTimeEvidence as BackendChannelProviderTimeEvidence
from magi.channels import ChannelSessionMapperProtocol as BackendChannelSessionMapperProtocol
from magi.channels import ChannelSessionMapping as BackendChannelSessionMapping
from magi.channels import ChannelTarget as BackendChannelTarget
from magi.channels import InboundMessage as BackendInboundMessage
from magi.channels import OutboundContent as BackendOutboundContent
from magi.channels.contracts import ChannelMessageDispatcherProtocol as BackendChannelContractsMessageDispatcherProtocol
from magi.channels.contracts import ChannelMessageDispatchOutcome as BackendChannelContractsMessageDispatchOutcome
from magi_plugin_sdk.channels import Channel as SdkChannel
from magi_plugin_sdk.channels import ChannelConfig as SdkChannelConfig
from magi_plugin_sdk.channels import ChannelAttachmentStoreProtocol as SdkChannelAttachmentStoreProtocol
from magi_plugin_sdk.channels import ChannelCursorClearProof as SdkChannelCursorClearProof
from magi_plugin_sdk.channels import ChannelInboundClearRequest as SdkChannelInboundClearRequest
from magi_plugin_sdk.channels import ChannelInboundClearStrategy as SdkChannelInboundClearStrategy
from magi_plugin_sdk.channels import ChannelInboundContext as SdkChannelInboundContext
from magi_plugin_sdk.channels import ChannelInboundRejectedError as SdkChannelInboundRejectedError
from magi_plugin_sdk.channels import ChannelInboundRejectionReason as SdkChannelInboundRejectionReason
from magi_plugin_sdk.channels import ChannelMessageDispatcherProtocol as SdkChannelMessageDispatcherProtocol
from magi_plugin_sdk.channels import ChannelMessageDispatchOutcome as SdkChannelMessageDispatchOutcome
from magi_plugin_sdk.channels import ChannelProviderTimeEvidence as SdkChannelProviderTimeEvidence
from magi_plugin_sdk.channels import ChannelSessionMapperProtocol as SdkChannelSessionMapperProtocol
from magi_plugin_sdk.channels import ChannelSessionMapping as SdkChannelSessionMapping
from magi_plugin_sdk.channels import ChannelTarget as SdkChannelTarget
from magi_plugin_sdk.channels import InboundMessage as SdkInboundMessage
from magi_plugin_sdk.channels import OutboundContent as SdkOutboundContent


def test_backend_channel_contracts_reexport_sdk_symbols() -> None:
    assert BackendChannel is SdkChannel
    assert BackendChannelConfig is SdkChannelConfig
    assert BackendChannelAttachmentStoreProtocol is SdkChannelAttachmentStoreProtocol
    assert BackendChannelCursorClearProof is SdkChannelCursorClearProof
    assert BackendChannelInboundClearRequest is SdkChannelInboundClearRequest
    assert BackendChannelInboundClearStrategy is SdkChannelInboundClearStrategy
    assert BackendChannelInboundContext is SdkChannelInboundContext
    assert BackendChannelInboundRejectedError is SdkChannelInboundRejectedError
    assert BackendChannelInboundRejectionReason is SdkChannelInboundRejectionReason
    assert BackendChannelMessageDispatcherProtocol is SdkChannelMessageDispatcherProtocol
    assert BackendChannelMessageDispatchOutcome is SdkChannelMessageDispatchOutcome
    assert BackendChannelProviderTimeEvidence is SdkChannelProviderTimeEvidence
    assert BackendChannelContractsMessageDispatcherProtocol is SdkChannelMessageDispatcherProtocol
    assert BackendChannelContractsMessageDispatchOutcome is SdkChannelMessageDispatchOutcome
    assert BackendChannelSessionMapperProtocol is SdkChannelSessionMapperProtocol
    assert BackendChannelSessionMapping is SdkChannelSessionMapping
    assert BackendChannelTarget is SdkChannelTarget
    assert BackendInboundMessage is SdkInboundMessage
    assert BackendOutboundContent is SdkOutboundContent


def test_control_port_contract_reexport_and_structural_typing() -> None:
    from magi.channels import (
        ChannelControlCommandResult as BackendResult,
        ChannelControlPortProtocol as BackendPort,
    )
    from magi.channels.contracts import (
        ChannelControlPortProtocol as BackendContractsPort,
    )
    from magi_plugin_sdk.channels import (
        ChannelControlCommandResult as SdkResult,
        ChannelControlPortProtocol as SdkPort,
    )

    # Backend re-exports the SAME objects as the SDK (no divergent copy).
    assert BackendResult is SdkResult
    assert BackendPort is SdkPort
    assert BackendContractsPort is SdkPort

    # The port is structurally typed — a stub with handle_command satisfies it.
    class _StubControlPort:
        async def handle_command(
            self, *, inbound_context, message, session_id, channel_type, external_chat_id, external_user_id,
        ):
            _ = inbound_context, message, session_id, channel_type, external_chat_id, external_user_id
            return None

    assert isinstance(_StubControlPort(), SdkPort)
    assert SdkResult(ack="✨ done", kind="session").ack == "✨ done"
    assert SdkResult().ack is None and SdkResult().kind == ""
