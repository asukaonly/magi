"""SDK Channel deliver/revise/retract extension tests."""
from __future__ import annotations

import pytest

from magi_plugin_sdk.delivery import DeliveryReceipt, DeliveryContent


def test_delivery_receipt_constructs_with_required_fields() -> None:
    receipt = DeliveryReceipt(
        channel_id="chat_sse:s1",
        external_message_id="msg_42",
        delivered_at_ms=1700000000000,
    )
    assert receipt.channel_id == "chat_sse:s1"
    assert receipt.external_message_id == "msg_42"
    assert receipt.delivered_at_ms == 1700000000000


def test_delivery_receipt_external_message_id_is_optional() -> None:
    """Some channels (e.g., fire-and-forget webhooks) have no external id."""
    receipt = DeliveryReceipt(
        channel_id="webhook:x",
        external_message_id=None,
        delivered_at_ms=1700000000000,
    )
    assert receipt.external_message_id is None


def test_delivery_receipt_is_frozen() -> None:
    receipt = DeliveryReceipt(
        channel_id="x", external_message_id=None, delivered_at_ms=1,
    )
    with pytest.raises(Exception):
        receipt.channel_id = "y"  # type: ignore[misc]


def test_delivery_content_constructs_with_text_only() -> None:
    content = DeliveryContent(text="hello world")
    assert content.text == "hello world"
    assert content.attachments == ()
    assert content.formatting == "markdown"


def test_delivery_content_constructs_with_attachments() -> None:
    content = DeliveryContent(
        text="see attached",
        attachments=({"kind": "image", "uri": "x.png"},),
        formatting="plaintext",
    )
    assert content.text == "see attached"
    assert len(content.attachments) == 1
    assert content.formatting == "plaintext"


def test_delivery_content_round_trips_through_to_dict() -> None:
    content = DeliveryContent(
        text="x", attachments=({"kind": "image", "uri": "a.png"},), formatting="markdown",
    )
    payload = content.to_dict()
    restored = DeliveryContent.from_dict(payload)
    assert restored == content


def test_delivery_receipt_round_trips_through_to_dict() -> None:
    original = DeliveryReceipt(
        channel_id="slack:U1", external_message_id="abc", delivered_at_ms=100,
    )
    payload = original.to_dict()
    restored = DeliveryReceipt.from_dict(payload)
    assert restored == original


# ---------------------------------------------------------------------------
# Task G.2 — Channel.deliver / revise / retract + capability flags
# ---------------------------------------------------------------------------

def test_channel_default_capability_flags_are_conservative() -> None:
    """A subclass that doesn't override flags should default to
    backward-compatible values: legacy send_message-only channels."""
    from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent

    class _LegacyChannel(Channel):
        @property
        def channel_type(self) -> str:
            return "legacy"

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def send_message(self, target, content):
            return None

        async def send_typing_indicator(self, target):
            return None

    ch = _LegacyChannel()
    assert ch.supports_streaming is False
    assert ch.supports_revision is False
    assert ch.supports_attachments is True  # most channels do


def test_channel_default_deliver_falls_back_to_send_message() -> None:
    """When a Channel implementation doesn't override deliver(), the
    default invokes send_message() and synthesizes a DeliveryReceipt
    with external_message_id=None. This preserves backward compat for
    existing plugins (Telegram, Weixin) without code changes."""
    import asyncio

    from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent
    from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

    sent: list = []

    class _LegacyChannel(Channel):
        @property
        def channel_type(self) -> str:
            return "legacy"

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def send_message(self, target, content):
            sent.append((target, content))

        async def send_typing_indicator(self, target):
            return None

    ch = _LegacyChannel()
    # ChannelTarget uses channel_type + external_chat_id (real SDK shape)
    target = ChannelTarget(channel_type="chat_sse", external_chat_id="s1")
    content = DeliveryContent(text="hello")

    receipt = asyncio.run(ch.deliver(target, content))

    assert len(sent) == 1
    assert isinstance(receipt, DeliveryReceipt)
    # channel_id in the receipt is derived from ChannelTarget.channel_type
    assert receipt.channel_id == "chat_sse"
    assert receipt.external_message_id is None  # legacy channel has no native id


def test_channel_default_revise_raises_not_supported() -> None:
    """A channel that doesn't override revise gets a NotImplementedError
    so the host knows to fall back to 'send new message' semantics."""
    import asyncio

    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

    class _LegacyChannel(Channel):
        @property
        def channel_type(self) -> str:
            return "legacy"

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def send_message(self, target, content):
            return None

        async def send_typing_indicator(self, target):
            return None

    ch = _LegacyChannel()
    receipt = DeliveryReceipt(channel_id="x", external_message_id="m1", delivered_at_ms=1)
    content = DeliveryContent(text="updated")

    with pytest.raises(NotImplementedError, match="revise"):
        asyncio.run(ch.revise(receipt, content))


def test_channel_default_retract_raises_not_supported() -> None:
    """Same pattern for retract."""
    import asyncio
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryReceipt

    class _LegacyChannel(Channel):
        @property
        def channel_type(self) -> str:
            return "legacy"

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def send_message(self, target, content):
            return None

        async def send_typing_indicator(self, target):
            return None

    ch = _LegacyChannel()
    receipt = DeliveryReceipt(channel_id="x", external_message_id="m1", delivered_at_ms=1)

    with pytest.raises(NotImplementedError, match="retract"):
        asyncio.run(ch.retract(receipt))


def test_channel_subclass_can_override_deliver_and_capability_flags() -> None:
    """A channel that DOES support revision sets the flag and overrides."""
    import asyncio
    from magi_plugin_sdk.channels import Channel, ChannelTarget
    from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

    class _ModernChannel(Channel):
        supports_revision = True
        supports_attachments = True

        @property
        def channel_type(self) -> str:
            return "modern"

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def send_message(self, target, content):
            return None

        async def send_typing_indicator(self, target):
            return None

        async def deliver(self, target, content):
            return DeliveryReceipt(
                channel_id=target.channel_type,
                external_message_id="native_msg_42",
                delivered_at_ms=999,
            )

        async def revise(self, receipt, content):
            return DeliveryReceipt(
                channel_id=receipt.channel_id,
                external_message_id=receipt.external_message_id,
                delivered_at_ms=1000,
            )

    ch = _ModernChannel()
    assert ch.supports_revision is True

    target = ChannelTarget(channel_type="modern", external_chat_id="u1")
    receipt = asyncio.run(ch.deliver(target, DeliveryContent(text="x")))
    assert receipt.external_message_id == "native_msg_42"
