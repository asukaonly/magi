"""Separate safe output preparation from an externally observable send."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt


@dataclass(frozen=True)
class PreparedDelivery:
    send: Callable[[], Awaitable[DeliveryReceipt]]
    retry_safe: bool


class DeliverySender(Protocol):
    async def prepare(self, target: ChannelTarget, content: DeliveryContent) -> PreparedDelivery: ...


class MessageChannel(Protocol):
    supports_idempotent_delivery: bool

    async def deliver(self, target: ChannelTarget, content: DeliveryContent) -> DeliveryReceipt: ...


class MessageDeliverySender:
    def __init__(self, channel: MessageChannel) -> None:
        self._channel = channel

    async def prepare(self, target: ChannelTarget, content: DeliveryContent) -> PreparedDelivery:
        async def send() -> DeliveryReceipt:
            return await self._channel.deliver(target, content)
        return PreparedDelivery(send, retry_safe=self._channel.supports_idempotent_delivery is True)
