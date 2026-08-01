from __future__ import annotations

import inspect

import pytest

from magi_plugin_sdk.channels import (
    ChannelInboundContext,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
    ChannelMessageDispatcherProtocol,
    InboundMessage,
)


def test_inbound_message_requires_provider_occurrence_time() -> None:
    with pytest.raises(TypeError):
        InboundMessage(  # type: ignore[call-arg]
            channel_type="telegram",
            external_chat_id="chat-1",
            external_user_id="user-1",
            external_message_id="message-1",
        )

    message = InboundMessage(
        channel_type="telegram",
        external_chat_id="chat-1",
        external_user_id="user-1",
        external_message_id="message-1",
        provider_occurred_at_ms=1_700_000_000_000,
    )
    assert message.provider_occurred_at_ms == 1_700_000_000_000


def test_dispatch_contract_requires_host_inbound_context() -> None:
    signature = inspect.signature(
        ChannelMessageDispatcherProtocol.dispatch_user_message
    )
    assert signature.parameters["inbound_context"].default is inspect.Parameter.empty
    assert "capture_inbound_context" in ChannelMessageDispatcherProtocol.__dict__


def test_terminal_rejection_exposes_stable_reason() -> None:
    error = ChannelInboundRejectedError(
        ChannelInboundRejectionReason.CLEARED_MESSAGE,
        "discard",
    )
    assert error.reason is ChannelInboundRejectionReason.CLEARED_MESSAGE
    assert str(error) == "discard"


def test_channel_inbound_context_is_immutable() -> None:
    context = ChannelInboundContext(
        provider_occurred_at_ms=1_700_000_000_000,
        clear_generation=2,
    )
    with pytest.raises((AttributeError, TypeError)):
        context.clear_generation = 3  # type: ignore[misc]
