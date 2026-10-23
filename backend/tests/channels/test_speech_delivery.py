"""One target receives one complete clip; unknown playback is never retried."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from magi_plugin_sdk.audio import AudioOutputTarget, AudioPlaybackReceipt, AudioPlaybackState
from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.transport import decode, encode

from magi.channels.audio_delivery import AudioDeliveryRouter
from magi.channels.speech_delivery import SpeechDeliverySender
from magi.delivery.worker import DeliveryRejected
from magi.speech.tts.engines import pcm_wav


def sender(state=AudioPlaybackState.ACCEPTED):
    playback = AudioPlaybackReceipt(AudioOutputTarget("home:speaker", "kitchen"), "d1", "p1", state)
    channel = SimpleNamespace(play_audio=AsyncMock(return_value=playback))
    synthesis = AsyncMock(return_value=pcm_wav(b"\0\0" * 800, 8000))
    return SpeechDeliverySender(AudioDeliveryRouter(SimpleNamespace(get_audio=lambda _: channel)), synthesis), channel, synthesis


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [AudioPlaybackState.ACCEPTED, AudioPlaybackState.PLAYING, AudioPlaybackState.COMPLETED])
async def test_preserves_submission_evidence_and_exact_destination(state):
    owner, channel, synthesis = sender(state)
    target = ChannelTarget("home:speaker", "kitchen", magi_session_id="conversation")
    result = await owner.prepare(target, DeliveryContent("Lights are off.", delivery_id="d1"))
    result = await result.send()
    assert result.playback.state is state
    assert result.delivery_id == "d1" and result.magi_session_id == "conversation"
    synthesis.assert_awaited_once_with("Lights are off.")
    channel.play_audio.assert_awaited_once_with(
        AudioOutputTarget("home:speaker", "kitchen"), synthesis.return_value, "d1",
    )
    assert DeliveryReceipt.from_dict(result.to_dict()) == result
    assert decode(encode(result)) == result
    assert owner.supports_idempotent_delivery is False


@pytest.mark.asyncio
async def test_synthesis_failure_cannot_start_playback():
    owner, channel, synthesis = sender()
    synthesis.side_effect = ValueError("model_missing")
    with pytest.raises(DeliveryRejected, match="SpeechSynthesisFailed"):
        await owner.prepare(ChannelTarget("home:speaker", "kitchen"), DeliveryContent("hello", delivery_id="d1"))
    channel.play_audio.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [AudioPlaybackState.UNKNOWN, AudioPlaybackState.STOPPED, AudioPlaybackState.STOP_REQUESTED])
async def test_nonconfirmed_playback_never_becomes_success(state):
    owner, _, _ = sender(state)
    with pytest.raises(RuntimeError, match="PlaybackOutcomeUnknown"):
        prepared = await owner.prepare(ChannelTarget("home:speaker", "kitchen"), DeliveryContent("hello", delivery_id="d1"))
        await prepared.send()


@pytest.mark.asyncio
async def test_cancelled_synthesis_does_not_play_late_result():
    owner, channel, synthesis = sender()
    started = asyncio.Event()
    async def pending(_):
        started.set()
        await asyncio.Event().wait()
    synthesis.side_effect = pending
    task = asyncio.create_task(owner.prepare(
        ChannelTarget("home:speaker", "kitchen"), DeliveryContent("hello", delivery_id="d1")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    channel.play_audio.assert_not_awaited()
