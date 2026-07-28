"""Runtime queue scheduling for durable chat user-turn attempts."""

from __future__ import annotations

import asyncio
import time

from ...events.contracts import UserMessageCommand
from ...events.runtime_queue import UserMessageScheduleOutcome
from ..contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatUserTurnDeliveryRecord,
)
from .contracts import (
    RuntimeUserMessageQueuePort,
    UserTurnDeliveryLedgerPort,
    UserTurnDeliveryScheduleFailure,
    UserTurnDeliveryScheduleResult,
)
from .envelope import parse_user_turn_runtime_envelope


class StaleUserTurnDeliveryError(RuntimeError):
    """Raised when the runtime queue is newer than the chat delivery ledger."""


class ChatUserTurnDeliveryScheduler:
    """Attach durable chat delivery attempts to the runtime command queue."""

    def __init__(
        self,
        *,
        chat_store: UserTurnDeliveryLedgerPort,
        runtime_command_queue: RuntimeUserMessageQueuePort,
    ) -> None:
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
                raise RuntimeError("Scheduled user-turn delivery has no runtime command ID")
            return UserTurnDeliveryScheduleResult(
                command_id=record.current_command_id,
                delivery_state=record.delivery_state,
            )
        if record.delivery_state != CHAT_DELIVERY_STATE_READY:
            raise RuntimeError(f"Unsupported user-turn delivery state: {record.delivery_state}")

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
            raise StaleUserTurnDeliveryError("Runtime queue is newer than the chat delivery ledger")
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
                failures.append(UserTurnDeliveryScheduleFailure(record=record, error=exc))
        return failures


__all__ = ["ChatUserTurnDeliveryScheduler", "StaleUserTurnDeliveryError"]
