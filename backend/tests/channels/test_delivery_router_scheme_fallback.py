"""DeliveryRouter scheme-fallback lookup + fanout_chunk tests.

Production registers channels under a *scheme* (e.g. "chat_sse",
"telegram") but ``ChannelTarget.channel_type`` may carry a composite
key (e.g. "chat_sse:s1", "telegram:42"). The router must fall back
to a scheme-only lookup when the composite key misses, while still
preferring an exact composite-key registration when one exists.

Also covers ``fanout_chunk``: parallel streaming fanout that mirrors
``fanout_deliver``'s error-isolation pattern.
"""
from __future__ import annotations

import pytest

from magi.channels.delivery_router import DeliveryRouter
from magi_plugin_sdk.channels import Channel, ChannelTarget
from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt


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


# === Scheme-fallback lookup tests ===

@pytest.mark.asyncio
async def test_scheme_fallback_resolves_composite_target_to_scheme_registered_channel():
    """Production: registry keyed by 'chat_sse', target is 'chat_sse:s1'."""
    sse = _RecordingChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": sse}))
    receipts = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[ChannelTarget(channel_type="chat_sse:s1", external_chat_id="u1")],
    )
    assert len(receipts) == 1
    # The channel saw the full composite target — preserves per-target context
    assert sse.delivered[0][0].channel_type == "chat_sse:s1"


@pytest.mark.asyncio
async def test_exact_composite_match_wins_over_scheme_fallback():
    """If registry has both 'chat_sse' and 'chat_sse:s1', exact match wins."""
    generic = _RecordingChannel("generic")
    specific = _RecordingChannel("specific")
    router = DeliveryRouter(channel_registry=_StubRegistry({
        "chat_sse": generic,
        "chat_sse:s1": specific,
    }))
    receipts = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[ChannelTarget(channel_type="chat_sse:s1", external_chat_id="u1")],
    )
    assert len(receipts) == 1
    assert specific.delivered and not generic.delivered


@pytest.mark.asyncio
async def test_no_scheme_no_fallback_returns_none():
    """target.channel_type without ':' shouldn't try a scheme split."""
    router = DeliveryRouter(channel_registry=_StubRegistry({}))
    receipts = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[ChannelTarget(channel_type="missing", external_chat_id="u1")],
    )
    assert receipts == []


# === fanout_chunk tests ===

class _RecordingChunkChannel(_RecordingChannel):
    def __init__(self, channel_type):
        super().__init__(channel_type)
        self.chunks = []

    async def deliver_chunk(self, target, chunk):
        self.chunks.append((target, chunk))


@pytest.mark.asyncio
async def test_fanout_chunk_routes_to_each_target_in_parallel():
    sse = _RecordingChunkChannel("chat_sse")
    tg = _RecordingChunkChannel("telegram")
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": sse, "telegram": tg}))
    await router.fanout_chunk(
        chunk=DeliveryChunk(text="ab", is_final=False, seq=0),
        targets=[
            ChannelTarget(channel_type="chat_sse:s1", external_chat_id="u1"),
            ChannelTarget(channel_type="telegram:42", external_chat_id="u1"),
        ],
    )
    assert sse.chunks and sse.chunks[0][1].text == "ab"
    assert tg.chunks and tg.chunks[0][1].text == "ab"


@pytest.mark.asyncio
async def test_fanout_chunk_isolates_per_channel_errors():
    sse = _RecordingChunkChannel("chat_sse")

    class _Broken(_RecordingChunkChannel):
        async def deliver_chunk(self, target, chunk):
            raise RuntimeError("boom")

    broken = _Broken("telegram")
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": sse, "telegram": broken}))
    # Should not raise; the broken channel's failure is swallowed and logged
    await router.fanout_chunk(
        chunk=DeliveryChunk(text="hi", is_final=False, seq=0),
        targets=[
            ChannelTarget(channel_type="chat_sse:s1", external_chat_id="u1"),
            ChannelTarget(channel_type="telegram:42", external_chat_id="u1"),
        ],
    )
    assert sse.chunks  # the working channel still got the chunk
