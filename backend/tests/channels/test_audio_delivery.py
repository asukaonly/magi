import io
import wave
from dataclasses import replace

import pytest

from magi_plugin_sdk.audio import (
    AudioClip, AudioOutputChannel, AudioOutputTarget, AudioPlaybackReceipt,
    AudioPlaybackState,
)
from magi.channels.audio_delivery import AudioDeliveryRouter
from magi.channels.registry import ChannelRegistry


class Output(AudioOutputChannel):
    channel_type = "test-speaker"

    def __init__(self):
        self.calls = 0
        self.started = False
        self.fail = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def clear_audio(self):
        pass

    async def play_audio(self, target, clip, request_id):
        self.calls += 1
        if self.fail:
            raise TimeoutError("Playback outcome is unknown")
        return AudioPlaybackReceipt(target, request_id, "p1", AudioPlaybackState.ACCEPTED)

    async def get_playback(self, receipt):
        return replace(receipt, state=AudioPlaybackState.UNKNOWN)

    async def stop_playback(self, receipt):
        return replace(receipt, state=AudioPlaybackState.STOP_REQUESTED)


def clip():
    data = io.BytesIO()
    with wave.open(data, "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        writer.writeframes(b"\0\0" * 160)
    return AudioClip(data.getvalue())


@pytest.mark.asyncio
async def test_output_channel_shares_lifecycle_but_never_receives_chat_fanout():
    registry = ChannelRegistry()
    channel = Output()
    registry.register(channel)
    assert registry.all_channels() == []
    assert registry.get(channel.channel_type) is None
    assert registry.get_audio(channel.channel_type) is channel
    assert registry.all_audio_channels() == [channel]
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Output())
    await registry.start_all()
    assert channel.started
    router = AudioDeliveryRouter(registry)
    result = await router.play(AudioOutputTarget(channel.channel_type, "living-room"), clip(), "r1")
    assert result.state == AudioPlaybackState.ACCEPTED
    assert (await router.status(result)).state == AudioPlaybackState.UNKNOWN
    assert (await router.stop(result)).state == AudioPlaybackState.STOP_REQUESTED
    await registry.stop_all()
    assert not channel.started


@pytest.mark.asyncio
async def test_audio_errors_do_not_trigger_retries_or_other_destinations():
    registry = ChannelRegistry()
    channel = Output()
    channel.fail = True
    registry.register(channel)
    router = AudioDeliveryRouter(registry)
    with pytest.raises(TimeoutError):
        await router.play(AudioOutputTarget(channel.channel_type, "living-room"), clip(), "r1")
    assert channel.calls == 1
    with pytest.raises(LookupError):
        await router.play(AudioOutputTarget("missing", "living-room"), clip(), "r1")
    with pytest.raises(ValueError, match="identifier"):
        await router.play(AudioOutputTarget(channel.channel_type, "living-room"), clip(), "")
    assert channel.calls == 1


@pytest.mark.asyncio
async def test_failed_audio_start_is_unavailable():
    class Broken(Output):
        async def start(self):
            raise RuntimeError("Device unavailable")

    registry = ChannelRegistry()
    registry.register(Broken())
    await registry.start_all()
    assert registry.get_audio("test-speaker") is None
    assert registry.all_audio_channels() == []


@pytest.mark.asyncio
async def test_unrelated_receipt_is_rejected():
    class Wrong(Output):
        async def get_playback(self, receipt):
            return replace(receipt, playback_id="another-playback")

    registry = ChannelRegistry()
    registry.register(Wrong())
    router = AudioDeliveryRouter(registry)
    receipt = await router.play(AudioOutputTarget("test-speaker", "room"), clip(), "r")
    with pytest.raises(ValueError, match="unrelated"):
        await router.status(receipt)
