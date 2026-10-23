"""Render durable text to one explicitly selected audio endpoint."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from magi_plugin_sdk.audio import AudioClip, AudioOutputTarget, AudioPlaybackState
from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

from ..delivery.worker import DeliveryRejected
from ..delivery.senders import PreparedDelivery
from .audio_delivery import AudioDeliveryRouter


class SpeechDeliverySender:
    """Confirm submission evidence while never replaying uncertain playback."""
    supports_idempotent_delivery = False

    def __init__(self, router: AudioDeliveryRouter,
                 synthesize: Callable[[str], Awaitable[AudioClip]]) -> None:
        self._router = router
        self._synthesize = synthesize

    async def prepare(self, target: ChannelTarget, content: DeliveryContent) -> PreparedDelivery:
        if not content.delivery_id or not content.text.strip():
            raise DeliveryRejected("SpeechContentMissing")
        try:
            clip = await self._synthesize(content.text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Synthesis has no device-side effect; failure is definite.
            raise DeliveryRejected("SpeechSynthesisFailed") from exc
        async def send() -> DeliveryReceipt:
            return await self._play(target, content, clip)
        return PreparedDelivery(send, retry_safe=False)

    async def _play(self, target: ChannelTarget, content: DeliveryContent, clip: AudioClip) -> DeliveryReceipt:
        receipt = await self._router.play(
            AudioOutputTarget(target.channel_type, target.external_chat_id),
            clip, content.delivery_id,
        )
        if receipt.state is AudioPlaybackState.FAILED:
            raise DeliveryRejected("PlaybackFailed")
        if receipt.state not in {
            AudioPlaybackState.ACCEPTED, AudioPlaybackState.PLAYING, AudioPlaybackState.COMPLETED,
        }:
            raise RuntimeError("PlaybackOutcomeUnknown")
        return DeliveryReceipt(
            channel_id=target.channel_type, external_message_id=receipt.playback_id,
            delivered_at_ms=int(time.time() * 1000), magi_session_id=target.magi_session_id,
            delivery_id=content.delivery_id, playback=receipt,
        )
