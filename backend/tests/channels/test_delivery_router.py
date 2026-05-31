"""DeliveryRouter fanout tests."""
from __future__ import annotations

import pytest

from magi.channels.delivery_router import DeliveryRouter
from magi_plugin_sdk.channels import Channel, ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt


class _RecordingChannel(Channel):
    """Test Channel that records calls + returns predictable receipts."""

    def __init__(self, channel_id: str) -> None:
        self._id = channel_id
        self.delivered: list[tuple[ChannelTarget, DeliveryContent]] = []
        self.revised: list = []
        self.retracted: list = []

    @property
    def channel_type(self) -> str:
        return self._id

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_message(self, target, content):
        return None

    async def send_typing_indicator(self, target):
        return None

    async def deliver(self, target, content):
        self.delivered.append((target, content))
        return DeliveryReceipt(
            channel_id=self._id,
            external_message_id=f"msg_{len(self.delivered)}",
            delivered_at_ms=1000 + len(self.delivered),
        )

    async def revise(self, receipt, content):
        self.revised.append((receipt, content))
        return receipt

    async def retract(self, receipt):
        self.retracted.append(receipt)


class _ChannelRegistryStub:
    """Stub ChannelRegistry that maps channel_id → Channel."""
    def __init__(self, channels: dict[str, Channel]) -> None:
        self._channels = channels

    def get(self, channel_id: str) -> Channel | None:
        return self._channels.get(channel_id)


@pytest.mark.asyncio
async def test_fanout_deliver_to_single_channel_returns_one_receipt() -> None:
    sse = _RecordingChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_ChannelRegistryStub({"chat_sse": sse}))
    content = DeliveryContent(text="hello")
    # channel_type is the scheme; per-run context rides on magi_session_id/magi_user_id.
    target = ChannelTarget(
        channel_type="chat_sse",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )

    receipts = await router.fanout_deliver(content=content, targets=[target])

    assert len(receipts) == 1
    assert receipts[0].channel_id == "chat_sse"
    assert sse.delivered == [(target, content)]


@pytest.mark.asyncio
async def test_fanout_deliver_to_two_channels_returns_two_receipts() -> None:
    sse = _RecordingChannel("chat_sse")
    telegram = _RecordingChannel("telegram")
    router = DeliveryRouter(channel_registry=_ChannelRegistryStub({
        "chat_sse": sse, "telegram": telegram,
    }))
    content = DeliveryContent(text="hello")
    targets = [
        ChannelTarget(
            channel_type="chat_sse",
            external_chat_id="",
            magi_session_id="s1",
            magi_user_id="u1",
        ),
        ChannelTarget(
            channel_type="telegram",
            external_chat_id="U2",
            magi_session_id="s1",
            magi_user_id="u2",
        ),
    ]

    receipts = await router.fanout_deliver(content=content, targets=targets)

    assert len(receipts) == 2
    assert {r.channel_id for r in receipts} == {"chat_sse", "telegram"}
    assert len(sse.delivered) == 1
    assert len(telegram.delivered) == 1


@pytest.mark.asyncio
async def test_fanout_deliver_skips_unknown_channel_and_continues() -> None:
    """An unknown channel_type is logged but does not abort the fanout —
    other channels still receive the content."""
    sse = _RecordingChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_ChannelRegistryStub({"chat_sse": sse}))
    content = DeliveryContent(text="hello")
    targets = [
        ChannelTarget(
            channel_type="chat_sse",
            external_chat_id="",
            magi_session_id="s1",
            magi_user_id="u1",
        ),
        ChannelTarget(
            channel_type="nonexistent",
            external_chat_id="x",
            magi_session_id="s1",
            magi_user_id="u2",
        ),
    ]

    receipts = await router.fanout_deliver(content=content, targets=targets)

    # Only the known channel produces a receipt.
    assert len(receipts) == 1
    assert receipts[0].channel_id == "chat_sse"


@pytest.mark.asyncio
async def test_fanout_deliver_continues_when_one_channel_raises() -> None:
    """A channel that raises during deliver does not abort the fanout;
    its receipt is omitted but other channels still get delivered."""
    sse = _RecordingChannel("chat_sse")

    class _BrokenChannel(_RecordingChannel):
        async def deliver(self, target, content):
            raise RuntimeError("channel broken")

    broken = _BrokenChannel("broken")
    router = DeliveryRouter(channel_registry=_ChannelRegistryStub({
        "chat_sse": sse, "broken": broken,
    }))
    targets = [
        ChannelTarget(
            channel_type="chat_sse",
            external_chat_id="",
            magi_session_id="s1",
            magi_user_id="u1",
        ),
        ChannelTarget(
            channel_type="broken",
            external_chat_id="x",
            magi_session_id="s1",
            magi_user_id="u2",
        ),
    ]

    receipts = await router.fanout_deliver(
        content=DeliveryContent(text="x"), targets=targets,
    )

    # Only the working channel produces a receipt.
    assert len(receipts) == 1
    assert receipts[0].channel_id == "chat_sse"


@pytest.mark.asyncio
async def test_fanout_retract_calls_each_channel_with_its_own_receipt() -> None:
    sse = _RecordingChannel("chat_sse")
    telegram = _RecordingChannel("telegram")
    router = DeliveryRouter(channel_registry=_ChannelRegistryStub({
        "chat_sse": sse, "telegram": telegram,
    }))
    receipts = [
        DeliveryReceipt(channel_id="chat_sse", external_message_id="m1", delivered_at_ms=1),
        DeliveryReceipt(channel_id="telegram", external_message_id="m2", delivered_at_ms=2),
    ]
    await router.fanout_retract(receipts=receipts)
    assert sse.retracted == [receipts[0]]
    assert telegram.retracted == [receipts[1]]


@pytest.mark.asyncio
async def test_fanout_retract_swallows_not_implemented_silently() -> None:
    """A channel that doesn't support retract should not abort the
    fanout — host logs but moves on. (Email-style channels.)"""

    class _NoRetractChannel(_RecordingChannel):
        async def retract(self, receipt):
            raise NotImplementedError("can't unsend email")

    email = _NoRetractChannel("email")
    router = DeliveryRouter(channel_registry=_ChannelRegistryStub({"email": email}))
    receipt = DeliveryReceipt(channel_id="email", external_message_id="m1", delivered_at_ms=1)

    # Must not raise.
    await router.fanout_retract(receipts=[receipt])
