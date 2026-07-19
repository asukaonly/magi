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
    sse = _RecordingChannel("chat_sse")
    telegram = _RecordingChannel("telegram")
    slack = _RecordingChannel("slack")

    router = DeliveryRouter(channel_registry=_StubRegistry({
        "chat_sse": sse, "telegram": telegram, "slack": slack,
    }))

    targets = [
        ChannelTarget(
            channel_type="chat_sse",
            external_chat_id="",
            magi_session_id="s1",
            magi_user_id="u1",
        ),
        ChannelTarget(
            channel_type="telegram",
            external_chat_id="",
            magi_session_id="s1",
            magi_user_id="u1",
        ),
        ChannelTarget(
            channel_type="slack",
            external_chat_id="",
            magi_session_id="s1",
            magi_user_id="u1",
        ),
    ]
    content = DeliveryContent(text="hello three places at once")

    result = await router.fanout_deliver(content=content, targets=targets)

    assert len(result.receipts) == 3
    assert all(
        receipt.external_message_id is not None
        for receipt in result.receipts
    )
    assert result.failures == ()
    assert len(sse.delivered) == 1
    assert len(telegram.delivered) == 1
    assert len(slack.delivered) == 1

    # Retract everything.
    await router.fanout_retract(receipts=list(result.receipts))
    assert len(sse.retracted) == 1
    assert len(telegram.retracted) == 1
    assert len(slack.retracted) == 1


@pytest.mark.asyncio
async def test_fanout_mixed_capability_channels() -> None:
    """Email can't retract — must not abort the fanout."""
    sse = _RecordingChannel("chat_sse")

    class _NoRetractEmail(_RecordingChannel):
        async def retract(self, receipt):
            raise NotImplementedError("can't unsend email")

    email = _NoRetractEmail("email")

    router = DeliveryRouter(channel_registry=_StubRegistry({
        "chat_sse": sse, "email": email,
    }))

    result = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[
            ChannelTarget(
                channel_type="chat_sse",
                external_chat_id="",
                magi_session_id="s1",
                magi_user_id="u1",
            ),
            ChannelTarget(
                channel_type="email",
                external_chat_id="u@x",
                magi_session_id="s1",
                magi_user_id="u1",
            ),
        ],
    )
    assert len(result.receipts) == 2
    assert result.failures == ()

    # Retract must not raise even though email can't.
    await router.fanout_retract(receipts=list(result.receipts))
    assert len(sse.retracted) == 1
    assert len(email.retracted) == 0  # NotImplementedError silently swallowed
