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
