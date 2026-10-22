"""Adapt control-owned notifications to the common delivery worker."""
from __future__ import annotations

from magi_plugin_sdk.delivery import DeliveryReceipt

from ..control.ask_delivery import AskDeliveryRepository
from ..delivery.outbox import DeliveryState, OutboundDelivery


class AskDeliveryQueue:
    def __init__(self, repository: AskDeliveryRepository) -> None:
        self._repository = repository

    async def claim_outbound_delivery(self, *, now_ms: int, message_id: str | None = None,
                                     lease_ms: int = 60_000) -> OutboundDelivery | None:
        if message_id is not None:
            raise ValueError("Question delivery is selected by its owner queue")
        item = await self._repository.claim(now_ms=now_ms, lease_ms=lease_ms)
        if item is None:
            return None
        return OutboundDelivery(
            delivery_id=item.delivery_id, message_id=item.request_id, session_id=item.session_id,
            user_id=item.intent.user_id, endpoint=item.intent.endpoint, content=item.intent.content,
            state=item.state, attempt_count=item.attempt_count, lease_token=item.lease_token,
            expires_at_ms=item.expires_at_ms, receipt=item.receipt,
        )

    async def begin_outbound_attempt(self, item: OutboundDelivery, *, retry_safe: bool, now_ms: int) -> bool:
        return await self._repository.begin(delivery_id=item.delivery_id, lease_token=item.lease_token,
                                            retry_safe=retry_safe, now_ms=now_ms)

    async def settle_outbound_delivery(self, item: OutboundDelivery, *, state: DeliveryState, now_ms: int,
                                       receipt: DeliveryReceipt | None = None, error: str | None = None,
                                       retry_at_ms: int = 0) -> bool:
        return await self._repository.settle(delivery_id=item.delivery_id, lease_token=item.lease_token,
            state=state, now_ms=now_ms, receipt=receipt, error=error, retry_at_ms=retry_at_ms)
