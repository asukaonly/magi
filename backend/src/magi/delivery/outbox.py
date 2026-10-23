"""Delivery attempts and persistence contracts, independent of transport/storage."""
from __future__ import annotations
from ..core.delivery_policy import LEASE_MS

from dataclasses import dataclass
from typing import Literal, Protocol

from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef
from magi_plugin_sdk.audio import AudioPlaybackState

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


@dataclass(frozen=True, slots=True)
class DeliveryStatus:
    delivery_id: str
    message_id: str
    session_id: str
    endpoint: EndpointRef
    state: DeliveryState
    attempt_count: int
    updated_at_ms: int
    playback_state: AudioPlaybackState | None = None


class DeliveryAttemptQueue(Protocol):
    """Business owner persists intent and outcome in its own transaction store."""

    async def claim_outbound_delivery(self, *, now_ms: int, message_id: str | None = None,
                                     lease_ms: int = LEASE_MS) -> OutboundDelivery | None: ...
    async def begin_outbound_attempt(self, item: OutboundDelivery, *, retry_safe: bool, now_ms: int) -> bool: ...
    async def settle_outbound_delivery(self, item: OutboundDelivery, *, state: DeliveryState, now_ms: int,
                                       receipt: DeliveryReceipt | None = None, error: str | None = None,
                                       retry_at_ms: int = 0) -> bool: ...


class DeliveryOutbox(DeliveryAttemptQueue, Protocol):
    """Read and cancellation access for committed chat message deliveries."""

    async def list_outbound_deliveries(self, *, message_id: str) -> list[OutboundDelivery]: ...
    async def cancel_run_outbound_deliveries(self, *, session_id: str, run_id: str, now_ms: int) -> None: ...
    async def list_run_outbound_deliveries(self, *, session_id: str, run_id: str) -> list[OutboundDelivery]: ...

    async def list_recent_outbound_status(self, *, limit: int = 50) -> list[DeliveryStatus]: ...
