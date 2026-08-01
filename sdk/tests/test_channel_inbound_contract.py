from __future__ import annotations

import inspect

import pytest

from magi_plugin_sdk.channels import (
    ChannelCursorClearProof,
    ChannelInboundContext,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
    ChannelMessageDispatcherProtocol,
    ChannelProviderTimeEvidence,
    InboundMessage,
)


def test_inbound_message_requires_one_explicit_admission_evidence() -> None:
    with pytest.raises(TypeError):
        InboundMessage(  # type: ignore[call-arg]
            channel_type="telegram",
            stream_id="account-1",
            external_chat_id="chat-1",
            external_user_id="user-1",
            external_message_id="message-1",
        )

    message = InboundMessage(
        channel_type="telegram",
        stream_id="account-1",
        external_chat_id="chat-1",
        external_user_id="user-1",
        external_message_id="message-1",
        admission_evidence=ChannelProviderTimeEvidence(
            provider_occurred_at_ms=1_700_000_000_000,
        ),
    )
    assert isinstance(message.admission_evidence, ChannelProviderTimeEvidence)

    cursor_message = InboundMessage(
        channel_type="weixin",
        stream_id="account-2",
        external_chat_id="chat-2",
        external_user_id="user-2",
        external_message_id="message-2",
        admission_evidence=ChannelCursorClearProof(clear_generation=3),
    )
    assert cursor_message.admission_evidence.clear_generation == 3


def test_dispatch_contract_requires_host_inbound_context() -> None:
    signature = inspect.signature(
        ChannelMessageDispatcherProtocol.dispatch_user_message
    )
    assert signature.parameters["inbound_context"].default is inspect.Parameter.empty
    assert "capture_inbound_context" in ChannelMessageDispatcherProtocol.__dict__
    assert "read_current_clear_generation" in ChannelMessageDispatcherProtocol.__dict__


def test_terminal_rejection_exposes_stable_reason() -> None:
    error = ChannelInboundRejectedError(
        ChannelInboundRejectionReason.CLEARED_MESSAGE,
        "discard",
    )
    assert error.reason is ChannelInboundRejectionReason.CLEARED_MESSAGE
    assert str(error) == "discard"


def test_channel_inbound_context_is_immutable() -> None:
    context = ChannelInboundContext(
        channel_type="telegram",
        stream_id="account-1",
        admission_evidence=ChannelProviderTimeEvidence(
            provider_occurred_at_ms=1_700_000_000_000,
        ),
        clear_generation=2,
    )
    with pytest.raises((AttributeError, TypeError)):
        context.clear_generation = 3  # type: ignore[misc]
