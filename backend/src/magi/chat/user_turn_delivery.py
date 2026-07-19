"""Durable scheduling and recovery for accepted chat user turns."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from ..core.logger import get_logger
from ..core.runtime_namespace import DEFAULT_RUNTIME_NAMESPACE
from ..events.contracts import UserMessageCommand
from ..events.first_context import (
    FIRST_CONTEXT_STORY_INTERACTION_KIND,
)
from ..events.recall_feedback import (
    RECALL_FEEDBACK_INTERACTION_KIND,
    RecallFeedbackRequest,
)
from ..events.runtime_queue import UserMessageScheduleOutcome
from ..i18n import t
from .contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatUserTurnDeliveryRecord,
)
from .first_context_projection import (
    extract_chat_projection_metadata,
    wait_for_first_context_memory_projection,
)
logger = get_logger(__name__)


class InvalidUserTurnDeliveryEnvelopeError(ValueError):
    """Raised when a persisted runtime envelope cannot be replayed safely."""


class StaleUserTurnDeliveryError(RuntimeError):
    """Raised when the runtime queue is newer than the chat delivery ledger."""


@dataclass(frozen=True, slots=True)
class UserTurnRuntimeEnvelope:
    """Validated replay input stored alongside one accepted user turn."""

    source: str
    user_id: str
    session_id: str
    turn_id: str
    message: str
    attachments: list[dict[str, Any]]
    workspace_path: str | None
    interaction_kind: str | None
    metadata: dict[str, Any]
    runtime_namespace: str


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


def parse_user_turn_runtime_envelope(
    record: ChatUserTurnDeliveryRecord,
) -> UserTurnRuntimeEnvelope:
    """Validate the durable runtime envelope against its owning chat row."""

    raw = record.runtime_envelope
    if not isinstance(raw, dict):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope must be an object"
        )
    user_id = _required_string(raw.get("user_id"), label="user_id")
    session_id = _required_string(raw.get("session_id"), label="session_id")
    turn_id = _required_string(raw.get("turn_id"), label="turn_id")
    if user_id != record.user_id:
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has the wrong user"
        )
    if session_id != record.session_id:
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has the wrong session"
        )
    if turn_id != record.turn_id:
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has the wrong turn"
        )

    message = raw.get("message")
    if not isinstance(message, str):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has an invalid message"
        )
    raw_attachments = raw.get("attachments")
    if not isinstance(raw_attachments, list) or not all(
        isinstance(item, dict) for item in raw_attachments
    ):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has invalid attachments"
        )
    if not message.strip() and not raw_attachments:
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope is empty"
        )
    raw_metadata = raw.get("metadata")
    if not isinstance(raw_metadata, dict):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has invalid metadata"
        )

    return UserTurnRuntimeEnvelope(
        source=_optional_string(raw.get("source")) or "api",
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        message=message,
        attachments=[dict(item) for item in raw_attachments],
        workspace_path=_optional_string(raw.get("workspace_path")),
        interaction_kind=_optional_string(raw.get("interaction_kind")),
        metadata=dict(raw_metadata),
        runtime_namespace=(
            _optional_string(raw.get("runtime_namespace"))
            or DEFAULT_RUNTIME_NAMESPACE
        ),
    )


class ChatUserTurnDeliveryScheduler:
    """Attach durable chat delivery attempts to the runtime command queue."""

    def __init__(self, *, chat_store: Any, runtime_command_queue: Any) -> None:
        self._chat_store = chat_store
        self._runtime_command_queue = runtime_command_queue

    async def schedule_record(
        self,
        record: ChatUserTurnDeliveryRecord,
    ) -> UserTurnDeliveryScheduleResult:
        """Schedule one ready attempt, preserving faster admission progress."""

        if record.delivery_state == CHAT_DELIVERY_STATE_TERMINAL:
            return UserTurnDeliveryScheduleResult(
                command_id=record.current_command_id,
                delivery_state=CHAT_DELIVERY_STATE_TERMINAL,
            )
        if record.delivery_state in {
            CHAT_DELIVERY_STATE_QUEUED,
            CHAT_DELIVERY_STATE_ADMITTED,
        }:
            if record.current_command_id is None:
                raise RuntimeError(
                    "Scheduled user-turn delivery has no runtime command ID"
                )
            return UserTurnDeliveryScheduleResult(
                command_id=record.current_command_id,
                delivery_state=record.delivery_state,
            )
        if record.delivery_state != CHAT_DELIVERY_STATE_READY:
            raise RuntimeError(
                f"Unsupported user-turn delivery state: {record.delivery_state}"
            )

        envelope = parse_user_turn_runtime_envelope(record)
        result = await self._runtime_command_queue.schedule_user_message(
            UserMessageCommand(
                source=envelope.source,
                user_id=envelope.user_id,
                session_id=envelope.session_id,
                turn_id=envelope.turn_id,
                message=envelope.message,
                attachments=envelope.attachments,
                workspace_path=envelope.workspace_path,
                runtime_namespace=envelope.runtime_namespace,
                metadata=envelope.metadata,
                created_at=float(record.created_at_ms) / 1000.0,
                correlation_id=f"user_message:{record.message_id}",
                delivery_attempt_no=record.delivery_attempt_no,
            )
        )
        if result.outcome is UserMessageScheduleOutcome.STALE:
            raise StaleUserTurnDeliveryError(
                "Runtime queue is newer than the chat delivery ledger"
            )
        command_id = int(result.command_id or 0)
        if command_id <= 0:
            raise RuntimeError("User-turn scheduling did not return a command ID")

        changed = await self._chat_store.mark_user_turn_delivery_queued(
            turn_id=record.turn_id,
            delivery_attempt_no=record.delivery_attempt_no,
            command_id=command_id,
            updated_at_ms=int(time.time() * 1000),
        )
        if changed:
            return UserTurnDeliveryScheduleResult(
                command_id=command_id,
                delivery_state=CHAT_DELIVERY_STATE_QUEUED,
            )

        current = await self._chat_store.get_user_turn_delivery(
            turn_id=record.turn_id,
        )
        if (
            current is not None
            and current.delivery_attempt_no == record.delivery_attempt_no
            and current.current_command_id == command_id
            and current.delivery_state
            in {
                CHAT_DELIVERY_STATE_QUEUED,
                CHAT_DELIVERY_STATE_ADMITTED,
                CHAT_DELIVERY_STATE_TERMINAL,
            }
        ):
            return UserTurnDeliveryScheduleResult(
                command_id=command_id,
                delivery_state=current.delivery_state,
            )
        raise RuntimeError(
            "User-turn runtime command could not be attached to its delivery attempt"
        )

    async def schedule_records(
        self,
        records: list[ChatUserTurnDeliveryRecord],
    ) -> list[UserTurnDeliveryScheduleFailure]:
        """Schedule records in chat order and retain failures as ready work."""

        failures: list[UserTurnDeliveryScheduleFailure] = []
        for record in records:
            try:
                await self.schedule_record(record)
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                failures.append(
                    UserTurnDeliveryScheduleFailure(record=record, error=exc)
                )
        return failures


class ChatUserTurnDeliveryRecoveryService:
    """Recover accepted user turns across process interruption boundaries."""

    def __init__(
        self,
        *,
        chat_store: Any,
        chat_read_service: Any,
        chat_projector: Any,
        delivery_scheduler: ChatUserTurnDeliveryScheduler,
        page_size: int = 250,
    ) -> None:
        self._chat_store = chat_store
        self._chat_read_service = chat_read_service
        self._chat_projector = chat_projector
        self._delivery_scheduler = delivery_scheduler
        self._page_size = max(1, min(int(page_size), 5000))

    async def recover_startup(self) -> UserTurnDeliveryRecoveryStats:
        """Invalidate pre-restart attempts, then replay unfinished turns."""

        stats = UserTurnDeliveryRecoveryStats()
        after: ChatUserTurnDeliveryRecord | None = None
        while True:
            page = await self._chat_read_service.alist_recoverable_user_turn_deliveries(
                limit=self._page_size,
                after=after,
            )
            if not page:
                return stats
            for record in page:
                stats.found += 1
                if await self._mark_terminal_surface(record):
                    stats.terminal += 1
                    continue

                try:
                    parse_user_turn_runtime_envelope(record)
                except InvalidUserTurnDeliveryEnvelopeError as exc:
                    await self._quarantine_invalid_delivery(record, error=exc)
                    stats.quarantined += 1
                    continue
                prepared = await self._chat_store.prepare_user_turn_delivery_attempt(
                    turn_id=record.turn_id,
                    expected_attempt_no=record.delivery_attempt_no,
                    updated_at_ms=int(time.time() * 1000),
                )
                if prepared is None:
                    current = await self._chat_store.get_user_turn_delivery(
                        turn_id=record.turn_id,
                    )
                    if current is None or current.delivery_state == CHAT_DELIVERY_STATE_TERMINAL:
                        continue
                    if current.delivery_state != CHAT_DELIVERY_STATE_READY:
                        continue
                    prepared = current
                stats.prepared += 1
                try:
                    prepared = await self._ensure_projection(prepared)
                    if prepared.projection_completed:
                        stats.projected += 1
                    await self._delivery_scheduler.schedule_record(prepared)
                    stats.scheduled += 1
                except InvalidUserTurnDeliveryEnvelopeError:
                    raise
                except Exception:
                    stats.failed += 1
                    logger.exception(
                        "Failed to recover accepted user turn",
                        turn_id=prepared.turn_id,
                        delivery_attempt_no=prepared.delivery_attempt_no,
                    )
            after = page[-1]

    async def retry_ready(self) -> UserTurnDeliveryRecoveryStats:
        """Retry ready attempts left by transient projection or queue failures."""

        stats = UserTurnDeliveryRecoveryStats()
        after: ChatUserTurnDeliveryRecord | None = None
        while True:
            page = await self._chat_read_service.alist_recoverable_user_turn_deliveries(
                limit=self._page_size,
                after=after,
            )
            if not page:
                return stats
            for record in page:
                try:
                    if await self._mark_terminal_surface(record):
                        stats.found += 1
                        stats.terminal += 1
                        continue
                    if record.delivery_state != CHAT_DELIVERY_STATE_READY:
                        continue
                    stats.found += 1
                    try:
                        parse_user_turn_runtime_envelope(record)
                    except InvalidUserTurnDeliveryEnvelopeError as exc:
                        await self._quarantine_invalid_delivery(
                            record,
                            error=exc,
                        )
                        stats.quarantined += 1
                        continue
                    projection_was_pending = not record.projection_completed
                    record = await self._ensure_projection(record)
                    if projection_was_pending and record.projection_completed:
                        stats.projected += 1
                    await self._delivery_scheduler.schedule_record(record)
                    stats.scheduled += 1
                except Exception:
                    stats.failed += 1
                    logger.exception(
                        "Failed to retry ready user turn",
                        turn_id=record.turn_id,
                        delivery_attempt_no=record.delivery_attempt_no,
                    )
            after = page[-1]

    async def _quarantine_invalid_delivery(
        self,
        record: ChatUserTurnDeliveryRecord,
        *,
        error: InvalidUserTurnDeliveryEnvelopeError,
    ) -> None:
        """Close one corrupt replay record without blocking unrelated chat."""

        now_ms = int(time.time() * 1000)
        changed = await self._chat_store.quarantine_invalid_user_turn_delivery(
            turn_id=record.turn_id,
            expected_attempt_no=record.delivery_attempt_no,
            user_message=t("chat.delivery.recovery_failed"),
            updated_at_ms=now_ms,
        )
        if not changed:
            current = await self._chat_store.get_user_turn_delivery(
                turn_id=record.turn_id,
            )
            if (
                current is None
                or current.delivery_state != CHAT_DELIVERY_STATE_TERMINAL
            ):
                raise RuntimeError(
                    "Invalid user-turn delivery could not be quarantined"
                )
        logger.error(
            "Quarantined invalid user-turn delivery envelope",
            turn_id=record.turn_id,
            delivery_attempt_no=record.delivery_attempt_no,
            error=str(error),
        )

    async def _ensure_projection(
        self,
        record: ChatUserTurnDeliveryRecord,
    ) -> ChatUserTurnDeliveryRecord:
        if record.projection_completed:
            return record
        envelope = parse_user_turn_runtime_envelope(record)
        recall_feedback = RecallFeedbackRequest.from_value(
            envelope.metadata.get("recall_feedback")
        )
        await self._chat_projector.project_user_message(
            message_id=record.message_id,
            user_id=envelope.user_id,
            session_id=envelope.session_id,
            turn_id=envelope.turn_id,
            content=envelope.message,
            created_at_ms=record.created_at_ms,
            interaction_kind=(
                RECALL_FEEDBACK_INTERACTION_KIND
                if recall_feedback is not None
                else envelope.interaction_kind
            ),
            metadata=extract_chat_projection_metadata(envelope.metadata),
        )
        if (
            envelope.interaction_kind == FIRST_CONTEXT_STORY_INTERACTION_KIND
            and not await wait_for_first_context_memory_projection(
                message_id=record.message_id,
            )
        ):
            raise RuntimeError(
                "First-context memory projection was not durably confirmed"
            )
        await self._chat_store.mark_user_turn_projection_completed(
            turn_id=record.turn_id,
            updated_at_ms=int(time.time() * 1000),
        )
        current = await self._chat_store.get_user_turn_delivery(
            turn_id=record.turn_id,
        )
        if current is None:
            raise RuntimeError("Projected user turn lost its delivery state")
        return current

    async def _mark_terminal_surface(
        self,
        record: ChatUserTurnDeliveryRecord,
    ) -> bool:
        changed = await self._chat_store.reconcile_user_turn_terminal_surface(
            turn_id=record.turn_id,
            expected_attempt_no=record.delivery_attempt_no,
            updated_at_ms=int(time.time() * 1000),
        )
        if changed:
            return True
        current = await self._chat_store.get_user_turn_delivery(
            turn_id=record.turn_id,
        )
        return (
            current is not None
            and current.delivery_state == CHAT_DELIVERY_STATE_TERMINAL
        )

def _required_string(value: object, *, label: str) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        raise InvalidUserTurnDeliveryEnvelopeError(
            f"Persisted user-turn runtime envelope has no {label}"
        )
    return normalized


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has a non-string field"
        )
    return value.strip() or None


__all__ = [
    "ChatUserTurnDeliveryRecoveryService",
    "ChatUserTurnDeliveryScheduler",
    "InvalidUserTurnDeliveryEnvelopeError",
    "StaleUserTurnDeliveryError",
    "UserTurnDeliveryRecoveryStats",
    "UserTurnDeliveryScheduleFailure",
    "UserTurnDeliveryScheduleResult",
    "UserTurnRuntimeEnvelope",
    "parse_user_turn_runtime_envelope",
]
