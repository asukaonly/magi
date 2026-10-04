"""SDK Channel deliver/revise/retract extension tests."""
from __future__ import annotations

import pytest

from magi_plugin_sdk.delivery import DeliveryReceipt, DeliveryContent


def test_delivery_content_round_trips_through_to_dict() -> None:
    content = DeliveryContent(
        text="x", attachments=({"kind": "image", "uri": "a.png"},), formatting="markdown",
    )
    payload = content.to_dict()
    restored = DeliveryContent.from_dict(payload)
    assert restored == content


@pytest.mark.parametrize("external_id", [None, "native-message-1"])
def test_delivery_receipt_wire_identity_keeps_session_scope_and_is_immutable(external_id):
    from dataclasses import FrozenInstanceError

    receipt = DeliveryReceipt(
        channel_id="channel-1",
        external_message_id=external_id,
        delivered_at_ms=100,
        magi_session_id="session-1",
    )
    expected = {
        "channel_id": "channel-1",
        "external_message_id": external_id,
        "delivered_at_ms": 100,
        "magi_session_id": "session-1",
    }
    assert receipt.to_dict() == expected
    assert DeliveryReceipt.from_dict(expected) == receipt
    with pytest.raises(FrozenInstanceError):
        receipt.channel_id = "other"


@pytest.fixture
def channel():
    from unittest.mock import AsyncMock
    from magi_plugin_sdk.channels import Channel

    class RecordingChannel(Channel):
        @property
        def channel_type(self):
            return "recording"

        async def start(self):
            pass

        async def stop(self):
            pass

        async def send_message(self, target, content):
            pass

        async def send_typing_indicator(self, target):
            pass

    instance = RecordingChannel()
    instance.send_message = AsyncMock()
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("send_fails", [False, True])
async def test_base_delivery_forwards_text_and_only_returns_receipt_after_send(
    channel, monkeypatch, send_fails
):
    from types import SimpleNamespace
    from magi_plugin_sdk.channels import ChannelTarget, OutboundContent

    monkeypatch.setattr("magi_plugin_sdk.channels.time", SimpleNamespace(time=lambda: 123.456))
    target = ChannelTarget(channel_type="recording", external_chat_id="room-1")
    content = DeliveryContent(text="hello")
    if send_fails:
        channel.send_message.side_effect = OSError("send failed")
        with pytest.raises(OSError, match="send failed"):
            await channel.deliver(target, content)
    else:
        receipt = await channel.deliver(target, content)
        assert receipt == DeliveryReceipt(
            channel_id="recording", external_message_id=None, delivered_at_ms=123456
        )
    channel.send_message.assert_awaited_once_with(target, OutboundContent(text="hello"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["revise", "retract"])
async def test_base_revision_operations_reject_without_advertising_support(channel, operation):
    assert (
        channel.supports_streaming,
        channel.supports_revision,
        channel.supports_attachments,
    ) == (False, False, True)
    receipt = DeliveryReceipt(
        channel_id="recording",
        external_message_id="native-1",
        delivered_at_ms=1,
        magi_session_id="session-1",
    )
    arguments = (receipt, DeliveryContent(text="updated")) if operation == "revise" else (receipt,)
    with pytest.raises(NotImplementedError, match=operation):
        await getattr(channel, operation)(*arguments)
    channel.send_message.assert_not_awaited()
