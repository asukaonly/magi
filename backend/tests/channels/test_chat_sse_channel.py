"""ChatSseChannel wrapper tests — making the existing SSE stream a
first-class DeliveryRouter target."""
from __future__ import annotations

import asyncio

import pytest

from magi.channels.chat_sse_channel import ChatSseChannel
from magi_plugin_sdk.channels import Channel, ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt


def test_chat_sse_channel_is_a_channel() -> None:
    ch = ChatSseChannel()
    assert isinstance(ch, Channel)


def test_chat_sse_channel_capability_flags() -> None:
    """chat SSE supports streaming + attachments, NOT revision (the
    frontend renders SSE chunks as immutable cards; edits would require
    a separate update event which Phase G doesn't model yet)."""
    ch = ChatSseChannel()
    assert ch.supports_streaming is True
    assert ch.supports_attachments is True
    assert ch.supports_revision is False


@pytest.mark.asyncio
async def test_chat_sse_channel_deliver_writes_to_emitter_and_returns_receipt() -> None:
    """deliver() pushes the content to the chat event emitter and
    returns a receipt with the chat session/turn ID as external_message_id."""
    emitted: list = []

    async def _emit(session_id: str, payload: dict) -> str:
        """Stub emitter that captures and returns a fake message_id."""
        emitted.append((session_id, payload))
        return f"chat_msg_{len(emitted)}"

    ch = ChatSseChannel(emit_to_chat=_emit)
    # channel_type is the composite "chat_sse:s1" — session_id is extracted from it
    target = ChannelTarget(channel_type="chat_sse:s1", external_chat_id="u1")
    content = DeliveryContent(text="hi from agent")

    receipt = await ch.deliver(target, content)

    assert len(emitted) == 1
    assert emitted[0][0] == "s1"  # session_id extracted from channel_type
    assert "hi from agent" in str(emitted[0][1])
    assert receipt.channel_id == "chat_sse:s1"
    assert receipt.external_message_id == "chat_msg_1"


@pytest.mark.asyncio
async def test_chat_sse_channel_send_message_legacy_path_still_works() -> None:
    """Legacy send_message (without DeliveryReceipt return) still works."""
    emitted = []

    async def _emit(session_id, payload):
        emitted.append((session_id, payload))
        return "x"

    ch = ChatSseChannel(emit_to_chat=_emit)
    from magi_plugin_sdk.channels import OutboundContent
    target = ChannelTarget(channel_type="chat_sse:s2", external_chat_id="u2")
    result = await ch.send_message(target, OutboundContent(text="legacy text"))
    assert result is None
    assert len(emitted) == 1
