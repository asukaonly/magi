"""Delivery attempts and persistence contracts, independent of transport/storage."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef

DeliveryState = Literal["pending", "leased", "sending", "succeeded", "uncertain", "failed", "expired", "cancelled"]


@dataclass(frozen=True, slots=True)
class OutboundDelivery:
    delivery_id: str
    message_id: str
    session_id: str
    user_id: str
    endpoint: EndpointRef
    content: DeliveryContent
    state: DeliveryState
    attempt_count: int
    lease_token: str | None
    expires_at_ms: int
    receipt: DeliveryReceipt | None


class DeliveryOutbox(Protocol):
    """Business owner persists intent and outcome in its own transaction store."""

    async def claim_outbound_delivery(self, *, now_ms: int, message_id: str | None = None,
                                     lease_ms: int = 60_000) -> OutboundDelivery | None: ...
    async def begin_outbound_attempt(self, item: OutboundDelivery, *, retry_safe: bool, now_ms: int) -> bool: ...
    async def settle_outbound_delivery(self, item: OutboundDelivery, *, state: DeliveryState, now_ms: int,
                                       receipt: DeliveryReceipt | None = None, error: str | None = None,
                                       retry_at_ms: int = 0) -> bool: ...
    async def list_outbound_deliveries(self, *, message_id: str) -> list[OutboundDelivery]: ...
