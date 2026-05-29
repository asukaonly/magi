"""Default ``Channel.deliver_chunk`` raises a helpful NotImplementedError.

Channels opt into streaming via ``supports_streaming = True`` and must
then override ``deliver_chunk``. The default implementation must not
silently drop chunks; it raises with a message that points the author
at the capability flag.
"""

from __future__ import annotations

import pytest

from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent
from magi_plugin_sdk.delivery import DeliveryChunk


class Bare(Channel):
    """Minimal concrete Channel that does NOT override deliver_chunk."""

    @property
    def channel_type(self) -> str:
        return "bare"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(
        self, target: ChannelTarget, content: OutboundContent
    ) -> None:
        pass

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        pass


@pytest.mark.asyncio
async def test_default_deliver_chunk_raises_with_capability_hint() -> None:
    """Default ``deliver_chunk`` raises NotImplementedError mentioning the
    subclass name and the ``supports_streaming`` capability flag."""
    instance = Bare()
    target = ChannelTarget(channel_type="bare", external_chat_id="c1")
    chunk = DeliveryChunk(text="hi", is_final=False, seq=0)

    with pytest.raises(NotImplementedError, match=r"Bare.*supports_streaming"):
        await instance.deliver_chunk(target, chunk)
