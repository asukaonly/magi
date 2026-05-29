"""Phase G end-to-end smoke: a single ExecutionResult fans out to ≥2
channels via DeliveryRouter; retract reaches each channel's retract."""
from __future__ import annotations

import pytest

from magi.channels.delivery_router import DeliveryRouter
from magi_plugin_sdk.channels import Channel, ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt


class _RecordingChannel(Channel):
    def __init__(self, channel_type: str) -> None:
        self._type = channel_type
        self.delivered: list = []
        self.retracted: list = []

    @property
    def channel_type(self):
        return self._type

    async def start(self):
        return None

    async def stop(self):
        return None

    async def send_message(self, target, content):
        return None

    async def send_typing_indicator(self, target):
        return None

    async def deliver(self, target, content):
        self.delivered.append((target, content))
        return DeliveryReceipt(
            channel_id=self._type,
            external_message_id=f"{self._type}_{len(self.delivered)}",
            delivered_at_ms=1000,
        )

    async def retract(self, receipt):
        self.retracted.append(receipt)


class _StubRegistry:
    def __init__(self, channels):
        self._c = channels

    def get(self, cid):
        return self._c.get(cid)


@pytest.mark.asyncio
async def test_fanout_to_three_channels_then_retract_all() -> None:
    sse = _RecordingChannel("chat_sse:s1")
    telegram = _RecordingChannel("telegram:42")
    slack = _RecordingChannel("slack:U7")

    router = DeliveryRouter(channel_registry=_StubRegistry({
        "chat_sse:s1": sse, "telegram:42": telegram, "slack:U7": slack,
    }))

    targets = [
        ChannelTarget(channel_type="chat_sse:s1", external_chat_id="u1"),
        ChannelTarget(channel_type="telegram:42", external_chat_id="u1"),
        ChannelTarget(channel_type="slack:U7", external_chat_id="u1"),
    ]
    content = DeliveryContent(text="hello three places at once")

    receipts = await router.fanout_deliver(content=content, targets=targets)

    assert len(receipts) == 3
    assert all(r.external_message_id is not None for r in receipts)
    assert len(sse.delivered) == 1
    assert len(telegram.delivered) == 1
    assert len(slack.delivered) == 1

    # Retract everything.
    await router.fanout_retract(receipts=receipts)
    assert len(sse.retracted) == 1
    assert len(telegram.retracted) == 1
    assert len(slack.retracted) == 1


@pytest.mark.asyncio
async def test_fanout_mixed_capability_channels() -> None:
    """Email can't retract — must not abort the fanout."""
    sse = _RecordingChannel("chat_sse:s1")

    class _NoRetractEmail(_RecordingChannel):
        async def retract(self, receipt):
            raise NotImplementedError("can't unsend email")

    email = _NoRetractEmail("email:u@x")

    router = DeliveryRouter(channel_registry=_StubRegistry({
        "chat_sse:s1": sse, "email:u@x": email,
    }))

    receipts = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[
            ChannelTarget(channel_type="chat_sse:s1", external_chat_id="u1"),
            ChannelTarget(channel_type="email:u@x", external_chat_id="u1"),
        ],
    )
    assert len(receipts) == 2

    # Retract must not raise even though email can't.
    await router.fanout_retract(receipts=receipts)
    assert len(sse.retracted) == 1
    assert len(email.retracted) == 0  # NotImplementedError silently swallowed
