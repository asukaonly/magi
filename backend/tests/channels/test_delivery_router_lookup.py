"""DeliveryRouter direct-lookup + fanout_chunk tests.

Phase G+2: ``DeliveryRouter._resolve`` is now a plain
``registry.get(channel_type)``. Composite-key fallback magic is gone;
every ChannelTarget carries its magi-side context in the dedicated
``magi_session_id`` / ``magi_user_id`` fields instead of encoding it
inside ``channel_type``.
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

    async def start(self): return None
    async def stop(self): return None
    async def send_message(self, target, content): return None
    async def send_typing_indicator(self, target): return None

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


def _target(channel_type: str, session_id: str = "s1", user_id: str = "u1"):
    return ChannelTarget(
        channel_type=channel_type,
        external_chat_id="",
        magi_session_id=session_id,
        magi_user_id=user_id,
    )


# === Direct lookup ===

@pytest.mark.asyncio
async def test_fanout_deliver_resolves_by_exact_channel_type():
    sse = _RecordingChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": sse}))
    result = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[_target("chat_sse")],
    )
    assert len(result.receipts) == 1
    assert result.failures == ()


@pytest.mark.asyncio
async def test_fanout_deliver_misses_when_channel_unknown():
    router = DeliveryRouter(channel_registry=_StubRegistry({}))
    result = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[_target("missing")],
    )
    assert result.receipts == ()
    assert len(result.failures) == 1
    assert result.failures[0].delivery_attempted is False


@pytest.mark.asyncio
async def test_no_scheme_fallback_for_composite_typed_targets():
    """Regression guard: a malformed composite key like 'chat_sse:s1'
    MUST miss (no fallback to 'chat_sse')."""
    sse = _RecordingChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": sse}))
    result = await router.fanout_deliver(
        content=DeliveryContent(text="hi"),
        targets=[_target("chat_sse:s1")],
    )
    assert result.receipts == ()
    assert len(result.failures) == 1
    assert result.failures[0].delivery_attempted is False


# === fanout_chunk ===

class _RecordingChunkChannel(_RecordingChannel):
    """Test channel that opts into streaming."""
    supports_streaming = True

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
        targets=[_target("chat_sse"), _target("telegram")],
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
    await router.fanout_chunk(
        chunk=DeliveryChunk(text="hi", is_final=False, seq=0),
        targets=[_target("chat_sse"), _target("telegram")],
    )
    assert sse.chunks


@pytest.mark.asyncio
async def test_fanout_chunk_isolates_registry_lookup_errors():
    sse = _RecordingChunkChannel("chat_sse")

    class _FailingRegistry(_StubRegistry):
        def get(self, cid):
            if cid == "broken":
                raise RuntimeError("registry unavailable")
            return super().get(cid)

    router = DeliveryRouter(
        channel_registry=_FailingRegistry({"chat_sse": sse})
    )
    await router.fanout_chunk(
        chunk=DeliveryChunk(text="hi", is_final=False, seq=0),
        targets=[_target("broken"), _target("chat_sse")],
    )

    assert sse.chunks


@pytest.mark.asyncio
async def test_fanout_chunk_skips_non_streaming_channels_silently():
    class _NonStreamingChannel(_RecordingChannel):
        async def deliver_chunk(self, target, chunk):
            raise AssertionError("must not be called on a non-streaming channel")

    tg = _NonStreamingChannel("telegram")
    sse = _RecordingChunkChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": sse, "telegram": tg}))
    await router.fanout_chunk(
        chunk=DeliveryChunk(text="ab", is_final=False, seq=0),
        targets=[_target("chat_sse"), _target("telegram")],
    )
    assert sse.chunks
