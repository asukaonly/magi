"""Explicit one-target audio dispatch, separate from automatic chat fanout."""

from __future__ import annotations

from magi_plugin_sdk.audio import (
    AudioClip, AudioOutputChannel, AudioOutputTarget, AudioPlaybackReceipt,
)

from .registry import ChannelRegistry


class AudioDeliveryRouter:
    """Route bounded audio without inferring destinations or retrying effects.

    Application services own authorization, admission and any durable request
    identity. An adapter error or timeout is not evidence that playback failed
    to start. The caller must reconcile it, never automatically repeat play.
    """

    def __init__(self, registry: ChannelRegistry) -> None:
        self._registry = registry

    def _channel(self, target: AudioOutputTarget) -> AudioOutputChannel:
        channel = self._registry.get_audio(target.channel_type)
        if channel is None:
            raise LookupError(f"Audio output channel is unavailable: {target.channel_type}")
        return channel

    @staticmethod
    def _validate(
        result: AudioPlaybackReceipt, target: AudioOutputTarget, request_id: str,
        playback_id: str | None = None,
    ) -> AudioPlaybackReceipt:
        if (
            not isinstance(result, AudioPlaybackReceipt)
            or result.target != target
            or result.request_id != request_id
            or (playback_id is not None and result.playback_id != playback_id)
        ):
            raise ValueError("Audio output returned an unrelated playback receipt")
        return result

    async def play(
        self, target: AudioOutputTarget, clip: AudioClip, request_id: str,
    ) -> AudioPlaybackReceipt:
        """Submit once to the chosen channel, preserving its actual evidence."""
        if not isinstance(clip, AudioClip):
            raise TypeError("Audio delivery requires a validated AudioClip")
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 512:
            raise ValueError("Audio request identifier is invalid")
        result = await self._channel(target).play_audio(target, clip, request_id)
        return self._validate(result, target, request_id)

    async def status(self, receipt: AudioPlaybackReceipt) -> AudioPlaybackReceipt:
        """Query the exact playback represented by the receipt."""
        result = await self._channel(receipt.target).get_playback(receipt)
        return self._validate(result, receipt.target, receipt.request_id, receipt.playback_id)

    async def stop(self, receipt: AudioPlaybackReceipt) -> AudioPlaybackReceipt:
        """Request stop without equating acceptance with completed playback."""
        result = await self._channel(receipt.target).stop_playback(receipt)
        return self._validate(result, receipt.target, receipt.request_id, receipt.playback_id)
