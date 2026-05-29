"""DeliveryRouter — Phase G fanout dispatcher.

Routes an ``AgentRun``'s reply to ≥1 channels via ``Channel.deliver``,
collects ``DeliveryReceipt``s for later ``revise`` / ``retract`` ops.

Replaces the 1:1 ``NotificationRelay`` polling pattern. NotificationRelay
remains as a backward-compat thin wrapper that delegates here.

Note on channel_id vs channel_type:
    The SDK's ``ChannelTarget`` uses ``channel_type`` (e.g. "telegram") as
    its primary identifier. Phase G extends this by supporting composite
    channel identifiers (e.g. "chat_sse:session_id", "telegram:U42") that
    encode both the channel type and the target within a single string.
    ``DeliveryRouter`` looks up channels from the registry using
    ``target.channel_type``, which may be a composite key when the caller
    registers channels under composite ids.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from ..core.logger import get_logger

if TYPE_CHECKING:
    from magi_plugin_sdk.channels import Channel, ChannelTarget
    from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

logger = get_logger(__name__)


class ChannelRegistryProtocol(Protocol):
    """Minimal interface DeliveryRouter needs from the ChannelRegistry."""

    def get(self, channel_id: str) -> "Channel | None": ...


class DeliveryRouter:
    """Fan out a single ``DeliveryContent`` to ≥1 ``ChannelTarget``s.

    Errors per channel are isolated — a failure in one channel does not
    abort delivery to others. Failed channels do NOT contribute a
    receipt to the return value; downstream callers should treat an
    absent receipt as "delivery to that channel failed; check logs".
    """

    __slots__ = ("_channel_registry",)

    def __init__(self, *, channel_registry: ChannelRegistryProtocol) -> None:
        self._channel_registry = channel_registry

    async def fanout_deliver(
        self,
        *,
        content: "DeliveryContent",
        targets: list["ChannelTarget"],
    ) -> list["DeliveryReceipt"]:
        """Deliver ``content`` to each target's channel in parallel.

        Returns the list of successful receipts (one per channel that
        accepted delivery). Failed / unknown channels are logged but
        not raised.

        Uses ``target.channel_type`` as the registry lookup key. When
        channels are registered under composite ids (e.g. "chat_sse:s1"),
        the caller should set ``channel_type`` to that composite id.
        """
        if not targets:
            return []

        async def _deliver_one(target: "ChannelTarget"):
            channel = self._channel_registry.get(target.channel_type)
            if channel is None:
                logger.warning(
                    "DeliveryRouter: no channel registered for channel_type=%r",
                    target.channel_type,
                )
                return None
            try:
                return await channel.deliver(target, content)
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel.deliver failed | channel_type=%r error=%s",
                    target.channel_type, exc,
                )
                return None

        results = await asyncio.gather(*(_deliver_one(t) for t in targets))
        return [r for r in results if r is not None]

    async def fanout_retract(
        self,
        *,
        receipts: list["DeliveryReceipt"],
    ) -> None:
        """Retract each receipt via its channel's ``retract``.

        Channels that don't support retract (NotImplementedError) are
        logged at info level and skipped — the host's caller should
        also send a ``(message retracted)`` correction message for
        those channels, but that's the caller's responsibility.
        """
        if not receipts:
            return

        async def _retract_one(receipt: "DeliveryReceipt"):
            channel = self._channel_registry.get(receipt.channel_id)
            if channel is None:
                logger.warning(
                    "DeliveryRouter: no channel for retract | channel_id=%r",
                    receipt.channel_id,
                )
                return
            try:
                await channel.retract(receipt)
            except NotImplementedError:
                logger.info(
                    "DeliveryRouter: channel does not support retract | channel_id=%r",
                    receipt.channel_id,
                )
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel.retract failed | channel_id=%r error=%s",
                    receipt.channel_id, exc,
                )

        await asyncio.gather(*(_retract_one(r) for r in receipts))


__all__ = ["DeliveryRouter", "ChannelRegistryProtocol"]
