"""Restart and retry recovery for durable chat user-turn delivery."""

from __future__ import annotations

import time

from ...core.logger import get_logger
from ...events.first_context import FIRST_CONTEXT_STORY_INTERACTION_KIND
from ...events.recall_feedback import (
    RECALL_FEEDBACK_INTERACTION_KIND,
    RecallFeedbackRequest,
)
from ...i18n import t
from ..contracts import (
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatUserTurnDeliveryRecord,
)
from ..first_context_projection import (
    extract_chat_projection_metadata,
    wait_for_first_context_memory_projection,
)
from .contracts import (
    RecoverableUserTurnReadPort,
    UserMessageProjectorPort,
    UserTurnDeliveryRecoveryStats,
    UserTurnDeliveryRecoveryStorePort,
)
from .envelope import (
    InvalidUserTurnDeliveryEnvelopeError,
    parse_user_turn_runtime_envelope,
)
from .scheduler import ChatUserTurnDeliveryScheduler

logger = get_logger(__name__)


class ChatUserTurnDeliveryRecoveryService:
    """Recover accepted user turns across process interruption boundaries."""

    def __init__(
        self,
        *,
        chat_store: UserTurnDeliveryRecoveryStorePort,
        chat_read_service: RecoverableUserTurnReadPort,
        chat_projector: UserMessageProjectorPort,
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
            if current is None or current.delivery_state != CHAT_DELIVERY_STATE_TERMINAL:
                raise RuntimeError("Invalid user-turn delivery could not be quarantined")
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
        recall_feedback = RecallFeedbackRequest.from_value(envelope.metadata.get("recall_feedback"))
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
            raise RuntimeError("First-context memory projection was not durably confirmed")
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
        return current is not None and current.delivery_state == CHAT_DELIVERY_STATE_TERMINAL


__all__ = ["ChatUserTurnDeliveryRecoveryService"]
