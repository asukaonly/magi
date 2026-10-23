"""Bounded recovery of durable message deliveries at one logical center."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryReceipt

from .outbox import DeliveryAttemptQueue
from .senders import DeliverySender
from ..core.delivery_policy import (MAX_ATTEMPTS, PREPARATION_TIMEOUT_SECONDS, SEND_TIMEOUT_SECONDS,
                     UNAVAILABLE_RETRY_MS, retry_delay_ms)


class DeliveryRejected(RuntimeError):
    """The sender has evidence the requested output was not accepted."""


class DeliveryWorker:
    """Consume owner-committed intents; never recompute targets or replay tool effects."""

    def __init__(self, *, outbox: DeliveryAttemptQueue, resolve: Callable[[str], DeliverySender | None],
                 clock_ms: Callable[[], int] | None = None, timeout_seconds: float = SEND_TIMEOUT_SECONDS,
                 preparation_timeout_seconds: float = PREPARATION_TIMEOUT_SECONDS) -> None:
        if not 0 < timeout_seconds <= SEND_TIMEOUT_SECONDS:
            raise ValueError("Delivery timeout must be at most thirty seconds")
        self._outbox = outbox
        self._resolve = resolve
        self._clock = clock_ms or (lambda: int(time.time() * 1000))
        self._timeout = timeout_seconds
        if not 0 < preparation_timeout_seconds <= PREPARATION_TIMEOUT_SECONDS:
            raise ValueError("Delivery preparation timeout exceeds the lease budget")
        self._preparation_timeout = preparation_timeout_seconds

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
                retry_at_ms=self._clock()+UNAVAILABLE_RETRY_MS,
            )
            return True
        target = ChannelTarget(
            channel_type=item.endpoint.registry_key, external_chat_id=item.endpoint.target_id,
            external_thread_id=item.endpoint.thread_id, magi_session_id=item.session_id, magi_user_id=item.user_id,
        )
        content = replace(item.content, delivery_id=item.delivery_id)
        try:
            remaining = max(0, (item.expires_at_ms - self._clock()) / 1000)
            prepared = await asyncio.wait_for(
                sender.prepare(target, content), timeout=min(self._preparation_timeout, remaining),
            )
        except DeliveryRejected as exc:
            await self._outbox.settle_outbound_delivery(item, state="failed", now_ms=self._clock(), error=str(exc))
            return True
        except (Exception, asyncio.CancelledError) as exc:
            # No provider effect has begun. Cancellation, timeout and transient
            # preparation errors remain safe to retry until the intent expires.
            await asyncio.shield(self._outbox.settle_outbound_delivery(
                item, state="pending", now_ms=self._clock(), error=type(exc).__name__,
                retry_at_ms=self._clock()+UNAVAILABLE_RETRY_MS,
            ))
            if isinstance(exc, asyncio.CancelledError):
                raise
            return True
        retry_safe = prepared.retry_safe
        if not await self._outbox.begin_outbound_attempt(item, retry_safe=retry_safe, now_ms=self._clock()):
            return True
        try:
            remaining = max(0, (item.expires_at_ms - self._clock()) / 1000)
            receipt = await asyncio.wait_for(prepared.send(), timeout=min(self._timeout, remaining))
            if not isinstance(receipt, DeliveryReceipt) or (
                receipt.channel_id != target.channel_type or receipt.delivery_id != item.delivery_id
                or receipt.magi_session_id != item.session_id
            ):
                raise ValueError("Delivery receipt does not identify the requested delivery")
        except DeliveryRejected as exc:
            await self._outbox.settle_outbound_delivery(
                item, state="failed", now_ms=self._clock(), error=str(exc),
            )
        except (Exception, asyncio.CancelledError) as exc:
            state = "pending" if retry_safe and item.attempt_count + 1 < MAX_ATTEMPTS else "uncertain"
            await asyncio.shield(self._outbox.settle_outbound_delivery(
                item, state=state, now_ms=self._clock(), error=type(exc).__name__,
                retry_at_ms=self._clock()+retry_delay_ms(item.attempt_count),
            ))
            if isinstance(exc, asyncio.CancelledError):
                raise
        else:
            await self._outbox.settle_outbound_delivery(item, state="succeeded", now_ms=self._clock(), receipt=receipt)
        return True
