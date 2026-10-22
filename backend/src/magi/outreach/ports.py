"""Domain-owned proactive delivery persistence contracts."""

from dataclasses import dataclass
from typing import Any, Protocol
from .contracts import OutboxEnqueueResult


class OutreachOutboxRepository(Protocol):
    async def enqueue(
        self,
        *,
        correlation_id: str,
        channel_scope: str,
        intent_fingerprint: str,
        intent_json: str,
        release_at_ms: int,
        created_at_ms: int,
    ) -> OutboxEnqueueResult: ...
    async def list_due(self, *, now_ms: int) -> list[dict[str, Any]]: ...
    async def mark_status(self, row_id: int, status: str) -> None: ...
    async def begin_delivery_attempt(self, row_id: int) -> bool: ...
    async def restore_pending_after_unattempted_delivery(
        self, row_id: int, *, intent_json: str
    ) -> bool: ...
    async def reschedule(self, row_id: int, *, release_at_ms: int) -> None: ...


class OutreachDeliveryLogRepository(Protocol):
    async def record(
        self, *, correlation_id: str, user_id: str, channel_type: str, delivered_at_ms: int
    ) -> None: ...
    async def was_delivered(self, correlation_id: str, channel_type: str) -> bool: ...
    async def count_for_user_since(self, user_id: str, since_ms: int) -> int: ...


@dataclass(frozen=True)
class OutreachRepositories:
    outbox: OutreachOutboxRepository
    delivery_log: OutreachDeliveryLogRepository
