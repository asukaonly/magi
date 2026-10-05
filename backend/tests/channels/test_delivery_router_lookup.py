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
@pytest.mark.parametrize("missing", ["missing", "chat_sse:s1"])
async def test_direct_channel_lookup_preserves_healthy_delivery_and_unattempted_failure(missing):
    channel = _RecordingChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": channel}))
    unknown, good = _target(missing), _target("chat_sse")
    content = DeliveryContent(text="hi")
    result = await router.fanout_deliver(content=content, targets=[unknown, good])
    assert channel.delivered == [(good, content)]
    assert result.receipts == (
        DeliveryReceipt(
            channel_id="chat_sse", external_message_id="chat_sse_1", delivered_at_ms=1000
        ),
    )
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.target == unknown
    assert failure.delivery_attempted is False
    assert isinstance(failure.error, LookupError)


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
async def test_chunk_fanout_enters_all_channels_before_any_completes():
    import asyncio

    release = asyncio.Event()

    class GatedChannel(_RecordingChunkChannel):
        def __init__(self, name):
            super().__init__(name)
            self.entered = asyncio.Event()

        async def deliver_chunk(self, target, chunk):
            self.entered.set()
            await release.wait()
            await super().deliver_chunk(target, chunk)

    first, second = GatedChannel("chat_sse"), GatedChannel("telegram")
    targets = [_target("chat_sse"), _target("telegram")]
    chunk = DeliveryChunk(text="ab", is_final=False, seq=4)
    router = DeliveryRouter(channel_registry=_StubRegistry({"chat_sse": first, "telegram": second}))
    task = asyncio.create_task(router.fanout_chunk(chunk=chunk, targets=targets))
    try:
        await asyncio.wait_for(
            asyncio.gather(first.entered.wait(), second.entered.wait()), timeout=2
        )
        assert not task.done()
        assert first.chunks == second.chunks == []
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=2)
    assert first.chunks == [(targets[0], chunk)]
    assert second.chunks == [(targets[1], chunk)]


@pytest.mark.asyncio
async def test_chunk_failure_is_attempted_and_does_not_block_healthy_channel():
    bad_attempts = []

    class Broken(_RecordingChunkChannel):
        async def deliver_chunk(self, target, chunk):
            bad_attempts.append((target, chunk))
            raise RuntimeError("injected channel failure")

    broken, healthy = Broken("broken"), _RecordingChunkChannel("chat_sse")
    router = DeliveryRouter(channel_registry=_StubRegistry({"broken": broken, "chat_sse": healthy}))
    bad_target, good_target = _target("broken"), _target("chat_sse")
    chunk = DeliveryChunk(text="hi", is_final=False, seq=4)
    await router.fanout_chunk(chunk=chunk, targets=[bad_target, good_target])
    assert bad_attempts == [(bad_target, chunk)]
    assert healthy.chunks == [(good_target, chunk)]


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
async def test_streaming_capability_gate_prevents_channel_invocation():
    class NonStreamingChannel(_RecordingChannel):
        def __init__(self, name):
            super().__init__(name)
            self.attempts = []

        async def deliver_chunk(self, target, chunk):
            self.attempts.append((target, chunk))

    disabled, enabled = NonStreamingChannel("telegram"), _RecordingChunkChannel("chat_sse")
    router = DeliveryRouter(
        channel_registry=_StubRegistry({"telegram": disabled, "chat_sse": enabled})
    )
    disabled_target, enabled_target = _target("telegram"), _target("chat_sse")
    chunk = DeliveryChunk(text="ab", is_final=False, seq=0)
    await router.fanout_chunk(chunk=chunk, targets=[disabled_target, enabled_target])
    assert disabled.attempts == []
    assert enabled.chunks == [(enabled_target, chunk)]
