"""Frozen notification intents for pending questions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef


@dataclass(frozen=True, slots=True)
class AskDeliveryIntent:
    user_id: str
    endpoint: EndpointRef
    content: DeliveryContent


@dataclass(frozen=True, slots=True)
class AskDeliveryAttempt:
    delivery_id: str
    request_id: str
    session_id: str
    intent: AskDeliveryIntent
    state: str
    attempt_count: int
    lease_token: str | None
    expires_at_ms: int
    receipt: DeliveryReceipt | None


class AskDeliveryRepository(Protocol):
    async def claim(self, *, now_ms: int, lease_ms: int) -> AskDeliveryAttempt | None: ...
    async def begin(self, *, delivery_id: str, lease_token: str | None, retry_safe: bool, now_ms: int) -> bool: ...
    async def settle(self, *, delivery_id: str, lease_token: str | None, state: str, now_ms: int,
                     receipt: DeliveryReceipt | None, error: str | None, retry_at_ms: int) -> bool: ...
