"""Typed collaborator boundaries for durable chat user-turn delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...events.contracts import UserMessageCommand
from ...events.runtime_queue import UserMessageScheduleResult
from ..contracts import ChatUserTurnDeliveryRecord


class UserTurnDeliveryLedgerPort(Protocol):
    """Delivery-ledger operations needed by queue scheduling."""

    async def mark_user_turn_delivery_queued(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool: ...

    async def get_user_turn_delivery(
        self,
        *,
        turn_id: str,
    ) -> ChatUserTurnDeliveryRecord | None: ...


class UserTurnDeliveryRecoveryStorePort(UserTurnDeliveryLedgerPort, Protocol):
    """Chat-store operations needed by restart recovery."""

    async def prepare_user_turn_delivery_attempt(
        self,
        *,
        turn_id: str,
        expected_attempt_no: int,
        updated_at_ms: int,
    ) -> ChatUserTurnDeliveryRecord | None: ...

    async def mark_user_turn_projection_completed(
        self,
        *,
        turn_id: str,
        updated_at_ms: int,
    ) -> None: ...

    async def reconcile_user_turn_terminal_surface(
        self,
        *,
        turn_id: str,
        expected_attempt_no: int,
        updated_at_ms: int,
    ) -> bool: ...

    async def quarantine_invalid_user_turn_delivery(
        self,
        *,
        turn_id: str,
        expected_attempt_no: int,
        user_message: str,
        updated_at_ms: int,
    ) -> bool: ...


class RuntimeUserMessageQueuePort(Protocol):
    """One command-queue operation used by chat delivery."""

    async def schedule_user_message(
        self,
        command: UserMessageCommand,
    ) -> UserMessageScheduleResult: ...


class RecoverableUserTurnReadPort(Protocol):
    """Read-side page needed by delivery recovery."""

    async def alist_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: ChatUserTurnDeliveryRecord | None = None,
    ) -> list[ChatUserTurnDeliveryRecord]: ...


class UserMessageProjectorPort(Protocol):
    """User-message projection operation needed before queue delivery."""

    async def project_user_message(
        self,
        *,
        message_id: str,
        user_id: str,
        session_id: str,
        turn_id: str,
        content: str,
        created_at_ms: int,
        interaction_kind: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class UserTurnDeliveryScheduleResult:
    """Result of attaching one delivery attempt to the runtime queue."""

    command_id: int | None
    delivery_state: str


@dataclass(frozen=True, slots=True)
class UserTurnDeliveryScheduleFailure:
    """One record left ready because scheduling did not complete."""

    record: ChatUserTurnDeliveryRecord
    error: BaseException


@dataclass(slots=True)
class UserTurnDeliveryRecoveryStats:
    """Counts from one recovery pass."""

    found: int = 0
    terminal: int = 0
    prepared: int = 0
    projected: int = 0
    scheduled: int = 0
    quarantined: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "found": self.found,
            "terminal": self.terminal,
            "prepared": self.prepared,
            "projected": self.projected,
            "scheduled": self.scheduled,
            "quarantined": self.quarantined,
            "failed": self.failed,
        }


__all__ = [
    "RecoverableUserTurnReadPort",
    "RuntimeUserMessageQueuePort",
    "UserMessageProjectorPort",
    "UserTurnDeliveryLedgerPort",
    "UserTurnDeliveryRecoveryStats",
    "UserTurnDeliveryRecoveryStorePort",
    "UserTurnDeliveryScheduleFailure",
    "UserTurnDeliveryScheduleResult",
]
