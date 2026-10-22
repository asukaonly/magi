"""Bounded recovery of durable message deliveries at one logical center."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

from .outbox import DeliveryOutbox


class DeliverySender(Protocol):
    supports_idempotent_delivery: bool

    async def deliver(self, target: ChannelTarget, content: DeliveryContent) -> DeliveryReceipt: ...


class DeliveryWorker:
    """Consume owner-committed intents; never recompute targets or replay tool effects."""

    def __init__(self, *, outbox: DeliveryOutbox, resolve: Callable[[str], DeliverySender | None],
                 clock_ms: Callable[[], int] | None = None, timeout_seconds: float = 30) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Delivery timeout must be at most thirty seconds")
        self._outbox = outbox
        self._resolve = resolve
        self._clock = clock_ms or (lambda: int(time.time() * 1000))
        self._timeout = timeout_seconds

    async def run_once(self, *, message_id: str | None = None) -> bool:
        item = await self._outbox.claim_outbound_delivery(now_ms=self._clock(), message_id=message_id)
        if item is None:
            return False
        try:
            sender = self._resolve(item.endpoint.registry_key)
        except Exception:
            sender = None
        if sender is None:
            await self._outbox.settle_outbound_delivery(
                item, state="pending", now_ms=self._clock(), error="ChannelUnavailable",
                retry_at_ms=self._clock()+5000,
            )
            return True
        retry_safe = sender.supports_idempotent_delivery is True
        if not await self._outbox.begin_outbound_attempt(item, retry_safe=retry_safe, now_ms=self._clock()):
            return True
        target = ChannelTarget(
            channel_type=item.endpoint.registry_key, external_chat_id=item.endpoint.target_id,
            external_thread_id=item.endpoint.thread_id, magi_session_id=item.session_id, magi_user_id=item.user_id,
        )
        content = replace(item.content, delivery_id=item.delivery_id)
        try:
            receipt = await asyncio.wait_for(sender.deliver(target, content), timeout=self._timeout)
            if not isinstance(receipt, DeliveryReceipt) or (
                receipt.channel_id != target.channel_type or receipt.delivery_id != item.delivery_id
                or receipt.magi_session_id != item.session_id
            ):
                raise ValueError("Delivery receipt does not identify the requested delivery")
        except (Exception, asyncio.CancelledError) as exc:
            state = "pending" if retry_safe and item.attempt_count < 4 else "uncertain"
            await asyncio.shield(self._outbox.settle_outbound_delivery(
                item, state=state, now_ms=self._clock(), error=type(exc).__name__,
                retry_at_ms=self._clock()+min(300_000, 1000 * 2 ** min(item.attempt_count, 8)),
            ))
            if isinstance(exc, asyncio.CancelledError):
                raise
        else:
            await self._outbox.settle_outbound_delivery(item, state="succeeded", now_ms=self._clock(), receipt=receipt)
        return True
