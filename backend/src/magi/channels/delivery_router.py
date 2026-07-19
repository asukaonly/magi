"""DeliveryRouter — Phase G fanout dispatcher.

Routes an ``AgentRun``'s reply to ≥1 channels via ``Channel.deliver``,
collects ``DeliveryReceipt``s for later ``revise`` / ``retract`` ops.

Replaces the 1:1 ``NotificationRelay`` polling pattern. NotificationRelay
remains as a backward-compat thin wrapper that delegates here.

Channel lookup (Phase G+2):
    ``DeliveryRouter`` resolves a target to a channel via a plain
    ``registry.get(target.channel_type)`` lookup. ``channel_type`` is
    the scheme only ("chat_sse", "telegram"), never a composite key.
    Per-run context (``magi_session_id``, ``magi_user_id``) rides on
    dedicated ``ChannelTarget`` fields and is consumed by the channel
    implementation, not by the router.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from ..core.logger import get_logger
from ..delivery.contracts import DeliveryFailure, DeliveryFanoutResult

if TYPE_CHECKING:
    from magi_plugin_sdk.channels import Channel, ChannelTarget
    from magi_plugin_sdk.control import ControlRequest
    from magi_plugin_sdk.delivery import DeliveryChunk, DeliveryContent, DeliveryReceipt

logger = get_logger(__name__)


class ChannelRegistryProtocol(Protocol):
    """Minimal interface DeliveryRouter needs from the ChannelRegistry."""

    def get(self, channel_id: str) -> "Channel | None": ...


class DeliveryRouter:
    """Fan out a single ``DeliveryContent`` to ≥1 ``ChannelTarget``s.

    Surface: ``fanout_deliver``, ``fanout_chunk``, ``fanout_retract``.

    Errors per channel are isolated — a failure in one channel does not
    abort delivery to others. Callers must inspect the explicit ``receipts``
    and ``failures`` fields.
    """

    __slots__ = ("_channel_registry",)

    def __init__(self, *, channel_registry: ChannelRegistryProtocol) -> None:
        self._channel_registry = channel_registry

    def _resolve(self, target_channel_type: str) -> "Channel | None":
        """Direct registry lookup. ``channel_type`` is the SCHEME — composite
        keys are not interpreted. (Phase G+2: every target carries per-run
        context in ``magi_session_id``/``magi_user_id`` fields instead of
        encoding it inside ``channel_type``.)
        """
        return self._channel_registry.get(target_channel_type)

    async def fanout_deliver(
        self,
        *,
        content: "DeliveryContent",
        targets: list["ChannelTarget"],
    ) -> DeliveryFanoutResult:
        """Deliver ``content`` to each target's channel in parallel.

        Returns successful receipts while retaining failed targets on
        ``result.failures``. Failed / unknown channels are logged but do
        not abort delivery to the remaining targets.

        Uses ``target.channel_type`` (the scheme, e.g. "chat_sse") as
        the registry lookup key.
        """
        if not targets:
            return DeliveryFanoutResult()

        async def _deliver_one(
            target: "ChannelTarget",
        ) -> tuple["DeliveryReceipt | None", DeliveryFailure | None]:
            try:
                channel = self._resolve(target.channel_type)
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel lookup failed "
                    "| channel_type=%r error=%s",
                    target.channel_type,
                    exc,
                )
                return None, DeliveryFailure(
                    target=target,
                    error=exc,
                    delivery_attempted=False,
                )
            if channel is None:
                error = LookupError(
                    f"No channel registered for channel type {target.channel_type!r}"
                )
                logger.warning(
                    "DeliveryRouter: no channel registered for channel_type=%r",
                    target.channel_type,
                )
                return None, DeliveryFailure(
                    target=target,
                    error=error,
                    delivery_attempted=False,
                )
            try:
                receipt = await channel.deliver(target, content)
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel.deliver failed | channel_type=%r error=%s",
                    target.channel_type, exc,
                )
                return None, DeliveryFailure(
                    target=target,
                    error=exc,
                    delivery_attempted=True,
                )
            if receipt is None:
                error = RuntimeError(
                    f"Channel {target.channel_type!r} returned no delivery receipt"
                )
                logger.warning(
                    "DeliveryRouter: channel.deliver returned no receipt "
                    "| channel_type=%r",
                    target.channel_type,
                )
                return None, DeliveryFailure(
                    target=target,
                    error=error,
                    delivery_attempted=True,
                )
            return receipt, None

        results = await asyncio.gather(*(_deliver_one(t) for t in targets))
        return DeliveryFanoutResult(
            receipts=tuple(
                receipt for receipt, _failure in results if receipt is not None
            ),
            failures=tuple(
                failure for _receipt, failure in results if failure is not None
            ),
        )

    async def fanout_chunk(
        self,
        *,
        chunk: "DeliveryChunk",
        targets: list["ChannelTarget"],
    ) -> None:
        """Stream one chunk to each target's channel in parallel.

        Errors per channel are isolated and logged — fanout never aborts.
        No receipts are returned (chunks don't carry identity; the final
        ``deliver()`` call is what produces the receipt the host stores).
        """
        if not targets:
            return

        async def _chunk_one(target: "ChannelTarget") -> None:
            try:
                channel = self._resolve(target.channel_type)
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel lookup failed for chunk "
                    "| channel_type=%r error=%s",
                    target.channel_type,
                    exc,
                )
                return
            if channel is None:
                logger.warning(
                    "DeliveryRouter: no channel registered for chunk | channel_type=%r",
                    target.channel_type,
                )
                return
            # Skip channels that don't opt into streaming — they only see
            # the assembled content via ``deliver()`` in fanout_deliver, so
            # forwarding chunks would either silently drop or (if a channel
            # over-implemented deliver_chunk) cause double-delivery once
            # fanout_deliver also fires.
            if not getattr(channel, "supports_streaming", False):
                return
            try:
                await channel.deliver_chunk(target, chunk)
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel.deliver_chunk failed | channel_type=%r error=%s",
                    target.channel_type, exc,
                )

        await asyncio.gather(*(_chunk_one(t) for t in targets))

    async def fanout_control_request(
        self,
        *,
        request: "ControlRequest",
        targets: list["ChannelTarget"],
    ) -> None:
        """Fan out a Phase H+2 control prompt (permission approval) to
        each target's channel in parallel.

        Channels that opted in via ``supports_control_requests = True``
        get ``Channel.deliver_control_request(target, request)``.
        Channels that didn't opt in (the default for any plugin that
        hasn't been migrated yet) are skipped silently — the host
        already publishes the prompt to ``runtime_notifications`` for
        the desktop side regardless, so a non-opted-in channel
        means "no extra surface, fall back to desktop" not "user is
        stuck". Same isolation guarantee as ``fanout_deliver``: a
        failure in one channel never aborts the others.

        No receipts are returned — the response path is the user
        replying through their normal inbound message channel
        (button-tap callback or ``/approve <short_id>`` text); the
        host's slash-command parser correlates back via ``short_id``.
        """
        if not targets:
            return

        async def _request_one(target: "ChannelTarget") -> None:
            try:
                channel = self._resolve(target.channel_type)
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel lookup failed for control request "
                    "| channel_type=%r error=%s",
                    target.channel_type,
                    exc,
                )
                return
            if channel is None:
                logger.warning(
                    "DeliveryRouter: no channel registered for control_request "
                    "| channel_type=%r",
                    target.channel_type,
                )
                return
            # Capability gate — fast path that avoids paying for the
            # NotImplementedError raise + catch in non-opted-in channels.
            if not getattr(channel, "supports_control_requests", False):
                return
            try:
                await channel.deliver_control_request(target, request)
            except NotImplementedError:
                # Defensive: plugin set the flag True but didn't override
                # the method — treat as "didn't opt in" and don't crash
                # the fanout for the channels that did opt in.
                logger.info(
                    "DeliveryRouter: channel reports control support but "
                    "raised NotImplementedError | channel_type=%r",
                    target.channel_type,
                )
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel.deliver_control_request failed "
                    "| channel_type=%r error=%s",
                    target.channel_type, exc,
                )

        await asyncio.gather(*(_request_one(t) for t in targets))

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

        async def _retract_one(receipt: "DeliveryReceipt") -> None:
            try:
                channel = self._resolve(receipt.channel_id)
            except Exception as exc:
                logger.warning(
                    "DeliveryRouter: channel lookup failed for retract "
                    "| channel_id=%r error=%s",
                    receipt.channel_id,
                    exc,
                )
                return
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


__all__ = [
    "ChannelRegistryProtocol",
    "DeliveryRouter",
]
