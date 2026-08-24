"""Session-run control operations for the chat task agent."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import FactQueue
from magi.agent.trace import now_wall_ms
from magi.chat.contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
)
from magi.core.logger import get_logger
from magi.events.events import EventTypes
from magi.agent.task_agents.common import UserMessagePayload
from magi.agent.task_agents.handlers.run_contracts import PendingTurn

from .cancel_protocol import is_strict_cancel_text
from .session_run_decisions import TurnSupersession

logger = get_logger(__name__)


class ChatSessionControlMixin:
    """Ingress input, cancel, deletion, and detach helpers."""

    _session_run_coordinator: Any
    _task_agent_manager: Any
    _postprocess_service: Any
    _chat_store: Any
    _execution_admission_lock: asyncio.Lock
    _fact_transfer_lock: asyncio.Lock
    _fact_queue: FactQueue
    _active_batch_facts: list[FactRecord]
    _fact_memory: list[FactRecord]
    _last_batch_facts: list[FactRecord]
    _facts_available: asyncio.Event
    _queue_space_available: asyncio.Event
    agent_id: str
    runtime_key: str
    agent_type: Any

    @asynccontextmanager
    async def _chat_execution_admission_boundary(self) -> AsyncIterator[None]:
        """Serialize run creation with ingress and user control mutations."""

        async with self._execution_admission_lock:
            yield

    async def plan_message_delete_runtime_turn_ids(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Split affected runtime turns into terminal and replay scopes."""

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_session_id:
            return (), ()

        def _fact_turn_id(fact: FactRecord) -> str:
            if fact.event_type != EventTypes.USER_MESSAGE:
                return ""
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            if (
                str(payload.get("session_id") or "").strip()
                != normalized_session_id
            ):
                return ""
            return str(payload.get("turn_id") or "").strip()

        async with self._chat_execution_admission_boundary():
            async with self._fact_transfer_lock:
                terminal_turn_ids = (
                    [normalized_turn_id] if normalized_turn_id else []
                )
                active_batch_turn_ids = [
                    value
                    for fact in self._active_batch_facts
                    if (value := _fact_turn_id(fact))
                ]
                active_batch_has_target = any(
                    value == normalized_turn_id
                    for value in active_batch_turn_ids
                )
                queued_turn_ids = [
                    value
                    for fact in self._fact_queue.snapshot()
                    if (value := _fact_turn_id(fact))
                ]
                queued_target = normalized_turn_id in queued_turn_ids
                active_run = self._session_run_coordinator.get_active_run(
                    normalized_session_id
                )
                pending_turn_ids = (
                    [
                        value
                        for pending_turn in active_run.pending_turns
                        if (value := str(pending_turn.turn_id or "").strip())
                    ]
                    if active_run is not None
                    else []
                )
                pending_target = normalized_turn_id in pending_turn_ids
                if (
                    pending_target or queued_target
                ) and not active_batch_has_target:
                    return tuple(terminal_turn_ids), ()
                active_root_turn_id = (
                    str(active_run.root_turn_id or "").strip()
                    if active_run is not None
                    else ""
                )
                if (
                    active_root_turn_id
                    and active_root_turn_id not in terminal_turn_ids
                ):
                    terminal_turn_ids.append(active_root_turn_id)
                replay_turn_ids = tuple(
                    dict.fromkeys(
                        value
                        for value in (
                            *active_batch_turn_ids,
                            *queued_turn_ids,
                            *pending_turn_ids,
                        )
                        if value and value not in terminal_turn_ids
                    )
                )
                return tuple(terminal_turn_ids), replay_turn_ids

    async def plan_message_delete_terminal_turn_ids(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> tuple[str, ...]:
        """Identify deliveries that must not survive one message deletion."""

        terminal_turn_ids, _ = await self.plan_message_delete_runtime_turn_ids(
            session_id=session_id,
            turn_id=turn_id,
        )
        return terminal_turn_ids

    def active_root_turn_id_for_message_delete(
        self,
        *,
        session_id: str,
    ) -> str | None:
        """Return the root whose assembled context may contain deleted history."""

        active_run = self._session_run_coordinator.get_active_run(session_id)
        if active_run is None:
            return None
        return str(active_run.root_turn_id or "").strip() or None

    async def discard_pending_turn_for_message_delete(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str | None,
        run_revision: int | None,
    ) -> bool:
        """Remove one unconsumed follow-up without interrupting its root run."""

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_session_id or not normalized_turn_id:
            return False

        def _matches_target_fact(fact: FactRecord) -> bool:
            if fact.event_type != EventTypes.USER_MESSAGE:
                return False
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            return (
                str(payload.get("session_id") or "").strip()
                == normalized_session_id
                and str(payload.get("turn_id") or "").strip()
                == normalized_turn_id
            )

        async with self._chat_execution_admission_boundary():
            async with self._fact_transfer_lock:
                if any(
                    _matches_target_fact(fact)
                    for fact in self._active_batch_facts
                ):
                    return False
                queued_target = any(
                    _matches_target_fact(fact)
                    for fact in self._fact_queue.snapshot()
                )
                active_run = self._session_run_coordinator.get_active_run(
                    normalized_session_id
                )
                pending_target = bool(
                    active_run is not None
                    and any(
                        str(pending_turn.turn_id or "").strip()
                        == normalized_turn_id
                        for pending_turn in active_run.pending_turns
                    )
                )
                if not pending_target and not queued_target:
                    return False

                if pending_target:
                    if active_run is None:
                        return False
                    normalized_run_id = str(run_id or "").strip()
                    if (
                        normalized_run_id
                        and active_run.run_id != normalized_run_id
                    ):
                        return False
                    if (
                        run_revision is not None
                        and active_run.revision != int(run_revision)
                    ):
                        return False
                    removed = await (
                        self._session_run_coordinator.discard_pending_turn_for_message_delete(
                            session_id=normalized_session_id,
                            turn_id=normalized_turn_id,
                            run_id=active_run.run_id,
                            revision=active_run.revision,
                        )
                    )
                    if removed is None:
                        return False

                self._fact_memory = [
                    fact
                    for fact in self._fact_memory
                    if not _matches_target_fact(fact)
                ]
                self._last_batch_facts = [
                    fact
                    for fact in self._last_batch_facts
                    if not _matches_target_fact(fact)
                ]
                self._fact_queue.remove_if(_matches_target_fact)
                if self._fact_queue.empty():
                    self._facts_available.clear()
                if not self._fact_queue.full():
                    self._queue_space_available.set()
                return True

    def matches_active_session_run(
        self,
        *,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        run_revision: int | None,
        match_turn_scope: bool,
    ) -> bool:
        """Return whether the requested durable run is still active."""
        active_run = self._session_run_coordinator.get_active_run(session_id)
        normalized_run_id = str(run_id or "").strip()
        if (
            active_run is not None
            and normalized_run_id
            and run_revision is not None
            and (
                active_run.run_id == normalized_run_id
                and active_run.revision == int(run_revision)
            )
        ):
            return True
        if (
            active_run is not None
            and match_turn_scope
            and normalized_run_id
            and active_run.run_id == normalized_run_id
        ):
            return True
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            return False
        if (
            active_run is not None
            and match_turn_scope
            and (
                active_run.root_turn_id == normalized_turn_id
                or any(
                    pending_turn.turn_id == normalized_turn_id
                    for pending_turn in active_run.pending_turns
                )
            )
        ):
            return True
        if not match_turn_scope:
            return False
        return any(
            fact.event_type == EventTypes.USER_MESSAGE
            and str(fact.payload.get("user_id") or "").strip()
            and str(fact.payload.get("session_id") or "").strip() == session_id
            and str(fact.payload.get("turn_id") or "").strip() == normalized_turn_id
            for fact in self.snapshot_inflight_facts()
        )

    def snapshot_pending_session_user_facts(
        self,
        *,
        session_id: str,
        excluded_turn_id: str | None,
    ) -> tuple[FactRecord, ...]:
        """Return full facts for pending turns that leave the run during deletion."""

        active_run = self._session_run_coordinator.get_active_run(session_id)
        if active_run is None:
            return ()
        excluded = str(excluded_turn_id or "").strip()
        pending_turn_ids = [
            str(pending_turn.turn_id or "").strip()
            for pending_turn in active_run.pending_turns
            if str(pending_turn.turn_id or "").strip()
            and str(pending_turn.turn_id or "").strip() != excluded
        ]
        if not pending_turn_ids:
            return ()
        fact_candidates = [
            *self._fact_memory,
            *list(self.snapshot_inflight_facts()),
        ]
        fact_by_turn: dict[str, FactRecord] = {}
        for fact in fact_candidates:
            if fact.event_type != EventTypes.USER_MESSAGE:
                continue
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            if str(payload.get("session_id") or "").strip() != session_id:
                continue
            turn_id = str(payload.get("turn_id") or "").strip()
            if turn_id in pending_turn_ids:
                fact_by_turn[turn_id] = fact
        missing_turn_ids = [
            turn_id for turn_id in pending_turn_ids if turn_id not in fact_by_turn
        ]
        if missing_turn_ids:
            raise RuntimeError(
                "Pending user turns cannot be durably replayed after message deletion"
            )
        return tuple(fact_by_turn[turn_id] for turn_id in pending_turn_ids)

    async def abandon_session_run_for_context_replay(
        self,
        *,
        session_id: str,
        replay_turn_ids: Sequence[str],
    ) -> bool:
        """Discard an unsafe run while preserving its user turn for replay."""

        normalized_session_id = str(session_id or "").strip()
        normalized_replay_turn_ids = {
            normalized
            for value in replay_turn_ids
            if (normalized := str(value or "").strip())
        }
        if not normalized_session_id or not normalized_replay_turn_ids:
            return False
        active_run = self._session_run_coordinator.get_active_run(
            normalized_session_id
        )
        if active_run is None:
            return False
        root_turn_id = str(active_run.root_turn_id or "").strip()
        if root_turn_id not in normalized_replay_turn_ids:
            raise RuntimeError(
                "Unsafe chat run is outside the prepared replay scope"
            )
        await _cancel_child_runs(
            session_id=normalized_session_id,
            run_id=active_run.run_id,
            run_revision=active_run.revision,
            strict=True,
        )
        await _cancel_owned_run_plan(
            session_id=normalized_session_id,
            run_id=active_run.run_id,
        )
        completed = self._session_run_coordinator.complete_run(
            session_id=normalized_session_id,
            run_id=active_run.run_id,
            revision=active_run.revision,
        )
        if not completed:
            raise RuntimeError("Unsafe chat run could not be cleared for replay")
        return True

    async def _request_ingress_cancel(self, fact: FactRecord) -> bool:
        """Handle a strict text cancel before the fact queue drains."""
        async with self._chat_execution_admission_boundary():
            return await self._request_ingress_cancel_at_admission_boundary(fact)

    async def _request_ingress_cancel_at_admission_boundary(
        self,
        fact: FactRecord,
    ) -> bool:
        """Apply an exact cancel control while the execution boundary is held."""

        cancellation_requested = False
        try:
            if fact.event_type != EventTypes.USER_MESSAGE:
                return False
            payload = fact.payload or {}
            session_id = str(payload.get("session_id") or "").strip()
            content = str(payload.get("content") or "")
            turn_id = str(payload.get("turn_id") or "").strip() or None
            if not (session_id and content and is_strict_cancel_text(content)):
                return False
            active_run = self._session_run_coordinator.get_active_run(session_id)
            if active_run is None or active_run.status not in ("running", "cancelling"):
                return False
            if not await self._mark_session_turn_cancelled(
                active_run,
                turn_id=active_run.root_turn_id,
                reason="user_cancel",
            ):
                return False
            self._session_run_coordinator.request_cancel(
                session_id=session_id,
                requested_by="user",
                reason="user_cancel",
                anchor_turn_id=active_run.root_turn_id,
            )
            cancellation_requested = True
            if turn_id:
                await self._postprocess_service.persist_turn_supersessions(
                    superseded_turns=[
                        TurnSupersession(
                            turn_id=turn_id,
                            anchor_turn_id=str(active_run.root_turn_id or turn_id),
                            reason="message",
                        )
                    ],
                    updated_at_ms=now_wall_ms(),
                )
            logger.info(
                "Strict cancel control requested active run cancellation",
                session_id=session_id,
                turn_id=turn_id,
            )
            return True
        except Exception as exc:
            logger.warning(
                "Strict cancel control failed",
                error=str(exc),
            )
            return cancellation_requested

    def _fact_targets_active_run(self, fact: FactRecord) -> bool:
        """Return whether one user fact belongs to an existing live run."""

        if fact.event_type != EventTypes.USER_MESSAGE:
            return False
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return False
        active_run = self._session_run_coordinator.get_active_run(session_id)
        return bool(
            active_run is not None
            and active_run.status in {"running", "cancelling"}
            and str(payload.get("turn_id") or "").strip()
            != str(active_run.root_turn_id or "").strip()
        )

    def _queue_active_run_input_at_admission_boundary(
        self,
        fact: FactRecord,
    ) -> bool:
        """Persist an ordinary user message on the currently active run."""

        if fact.event_type != EventTypes.USER_MESSAGE:
            return False
        payload_dict = fact.payload if isinstance(fact.payload, dict) else {}
        payload = UserMessagePayload.from_dict(
            payload_dict,
            fallback_user_id=self.agent_id,
        )
        if not payload.session_id or not payload.content:
            return False
        if any(
            (
                payload.attachments,
                payload.reply_to_message_id,
                payload.recall_feedback,
                payload.first_context,
                payload.skill_invocation,
                payload.reasoning_preference,
            )
        ):
            return False
        active_run = self._session_run_coordinator.get_active_run(payload.session_id)
        if active_run is None or active_run.status not in {"running", "cancelling"}:
            return False
        if payload.turn_id and payload.turn_id == active_run.root_turn_id:
            return False
        decision = self._session_run_coordinator.handle_user_turn(
            payload,
            source_fact=fact,
        )
        return decision.run_disposition == "message"

    async def _release_pending_inputs(
        self,
        session_id: str,
        pending_inputs: Sequence[PendingTurn],
    ) -> None:
        """Move unconsumed run inputs back to the durable runtime queue.

        The chat delivery row, not an in-memory ``FactRecord``, owns retry
        identity and the complete original envelope.  The caller atomically
        captures these entries while completing the old run, then checkpoints
        that completion before invoking this method.
        """
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        if not pending_inputs:
            return
        chat_store = self._chat_store
        if chat_store is None:
            raise RuntimeError("Chat store is required to release pending inputs")
        from magi.core.runtime_bindings import require_runtime_command_queue
        from magi.chat.user_turn_delivery import ChatUserTurnDeliveryScheduler

        scheduler = ChatUserTurnDeliveryScheduler(
            chat_store=chat_store,
            runtime_command_queue=require_runtime_command_queue(),
        )
        for pending_turn in pending_inputs:
            record = await chat_store.get_user_turn_delivery(
                turn_id=pending_turn.turn_id,
            )
            if record is None:
                raise RuntimeError(
                    f"Pending input '{pending_turn.turn_id}' has no delivery record"
                )
            if record.delivery_state == CHAT_DELIVERY_STATE_TERMINAL:
                continue
            if record.delivery_state == CHAT_DELIVERY_STATE_ADMITTED:
                prepared = await chat_store.prepare_user_turn_delivery_attempt(
                    turn_id=record.turn_id,
                    expected_attempt_no=record.delivery_attempt_no,
                    updated_at_ms=now_wall_ms(),
                )
                if prepared is None:
                    prepared = await chat_store.get_user_turn_delivery(
                        turn_id=record.turn_id,
                    )
                if prepared is None:
                    raise RuntimeError(
                        f"Pending input '{record.turn_id}' lost its delivery record"
                    )
                record = prepared
            if record.delivery_state not in {
                CHAT_DELIVERY_STATE_ADMITTED,
                CHAT_DELIVERY_STATE_READY,
                CHAT_DELIVERY_STATE_QUEUED,
                CHAT_DELIVERY_STATE_TERMINAL,
            }:
                raise RuntimeError(
                    f"Pending input '{record.turn_id}' cannot be released from "
                    f"delivery state '{record.delivery_state}'"
                )
            if record.delivery_state != CHAT_DELIVERY_STATE_TERMINAL:
                try:
                    await scheduler.schedule_record(record)
                except Exception:
                    current = await chat_store.get_user_turn_delivery(
                        turn_id=record.turn_id,
                    )
                    if (
                        current is None
                        or current.delivery_state != CHAT_DELIVERY_STATE_READY
                    ):
                        raise
                    logger.warning(
                        "Pending input remains ready for background retry",
                        session_id=normalized_session_id,
                        turn_id=record.turn_id,
                        delivery_attempt_no=current.delivery_attempt_no,
                    )

    async def request_session_cancel(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        requested_by: str,
        reason: str = "user_cancel",
        anchor_turn_id: str | None = None,
    ) -> dict[str, object] | None:
        """Cancel one exact user turn across queued and running stages."""

        normalized_session_id = str(session_id or "").strip()
        normalized_user_id = str(user_id or "").strip() or None
        normalized_anchor_turn_id = str(anchor_turn_id or "").strip()
        if not normalized_session_id:
            return None

        async with self._chat_execution_admission_boundary():
            active_run = self._session_run_coordinator.get_active_run(
                normalized_session_id
            )
            cancellation_turn_id = str(
                normalized_anchor_turn_id
                or (active_run.root_turn_id if active_run is not None else "")
                or ""
            ).strip()
            if not cancellation_turn_id:
                return None

            target_matches_active_root = bool(
                active_run is not None
                and str(active_run.root_turn_id or "").strip()
                == cancellation_turn_id
            )
            if not await self._mark_session_turn_cancelled(
                active_run,
                turn_id=cancellation_turn_id,
                reason=reason,
                expected_session_id=normalized_session_id,
                expected_user_id=normalized_user_id,
            ):
                return None
            if target_matches_active_root:
                cancelling_run = self._session_run_coordinator.request_cancel(
                    session_id=normalized_session_id,
                    requested_by=requested_by,
                    reason=reason,
                    anchor_turn_id=cancellation_turn_id,
                )
                if cancelling_run is not None:
                    active_run = cancelling_run

        if not target_matches_active_root:
            await self.discard_pending_turn_for_message_delete(
                session_id=normalized_session_id,
                turn_id=cancellation_turn_id,
                run_id=active_run.run_id if active_run is not None else None,
                run_revision=active_run.revision if active_run is not None else None,
            )
            await self._postprocess_service.emit_execution_control_notification(
                user_id=normalized_user_id or self.agent_id,
                session_id=normalized_session_id,
                turn_id=cancellation_turn_id,
                run_id=None,
                state="cancelled",
                can_cancel=False,
                label="Run cancelled",
            )
            return {
                "session_id": normalized_session_id,
                "turn_id": cancellation_turn_id,
                "run_id": None,
                "revision": 0,
                "status": "cancelled",
                "cancel_reason": reason,
                "cancel_requested_by": requested_by,
                "cancel_anchor_turn_id": cancellation_turn_id,
                "cancelled_child_ids": [],
            }

        if active_run is None:
            raise RuntimeError("Active chat run disappeared during cancellation")
        cancelled_child_ids = await _cancel_child_runs(
            session_id=normalized_session_id,
            run_id=active_run.run_id,
            run_revision=active_run.revision,
            strict=reason in {"memory_clear", "privacy_delete", "privacy_context_changed"},
        )
        await _cancel_owned_run_plan(
            session_id=normalized_session_id,
            run_id=active_run.run_id,
        )
        await self._postprocess_service.mark_user_turn_delivery_terminal_if_persisted(
            turn_id=cancellation_turn_id,
            source_fact=None,
        )
        completed, pending_inputs = (
            self._session_run_coordinator.complete_run_with_pending_inputs(
                session_id=normalized_session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
            )
        )
        if completed:
            await self._postprocess_service.release_pending_inputs_after_run_completion(
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                pending_inputs=pending_inputs,
            )
        await self._postprocess_service.emit_execution_control_notification(
            user_id=normalized_user_id or self.agent_id,
            session_id=normalized_session_id,
            turn_id=cancellation_turn_id,
            run_id=active_run.run_id,
            state="cancelled",
            can_cancel=False,
            label="Run cancelled",
        )
        current_run = (
            self._session_run_coordinator.get_active_run(normalized_session_id)
            or active_run
        )
        return {
            "session_id": normalized_session_id,
            "turn_id": cancellation_turn_id,
            "run_id": current_run.run_id,
            "revision": current_run.revision,
            "status": current_run.status,
            "cancel_reason": current_run.cancel_reason,
            "cancel_requested_by": current_run.cancel_requested_by,
            "cancel_anchor_turn_id": current_run.cancel_anchor_turn_id,
            "cancelled_child_ids": cancelled_child_ids,
        }

    async def _mark_session_turn_cancelled(
        self,
        active_run: Any | None,
        *,
        turn_id: str | None = None,
        reason: str | None = None,
        expected_session_id: str | None = None,
        expected_user_id: str | None = None,
    ) -> bool:
        chat_store = self._chat_store
        if chat_store is None:
            return True
        normalized_turn_id = str(
            turn_id
            or (active_run.cancel_anchor_turn_id if active_run is not None else None)
            or (active_run.root_turn_id if active_run is not None else None)
            or "",
        ).strip()
        if not normalized_turn_id:
            return True
        existing_turn = await chat_store.get_turn(normalized_turn_id)
        if existing_turn is None:
            return False
        normalized_session_id = str(expected_session_id or "").strip()
        normalized_user_id = str(expected_user_id or "").strip()
        if (
            normalized_session_id
            and existing_turn.session_id != normalized_session_id
        ):
            return False
        if normalized_user_id and existing_turn.user_id != normalized_user_id:
            return False
        if str(existing_turn.status or "").strip().lower() == "cancelled":
            return True
        completed_at_ms = now_wall_ms()
        cancellation_reason = str(
            reason
            or (active_run.cancel_reason if active_run is not None else None)
            or "user_cancel"
        )
        cancelled = await chat_store.cancel_user_turn_delivery_if_active(
            turn_id=normalized_turn_id,
            expected_session_id=normalized_session_id or None,
            expected_user_id=normalized_user_id or None,
            run_id=(
                existing_turn.run_id
                or (active_run.run_id if active_run is not None else None)
            ),
            run_revision=(
                existing_turn.run_revision
                or int(active_run.revision if active_run is not None else 0)
            ),
            reason=cancellation_reason,
            updated_at_ms=completed_at_ms,
        )
        if not cancelled:
            current_turn = await chat_store.get_turn(normalized_turn_id)
            return bool(
                current_turn is not None
                and (
                    not normalized_session_id
                    or current_turn.session_id == normalized_session_id
                )
                and (
                    not normalized_user_id
                    or current_turn.user_id == normalized_user_id
                )
                and str(current_turn.status or "").strip().lower() == "cancelled"
            )
        await self._postprocess_service.emit_cancelled_turn_trace(
            user_id=existing_turn.user_id,
            session_id=existing_turn.session_id,
            turn_id=existing_turn.turn_id,
            started_at_ms=existing_turn.created_at_ms,
            cancelled_at_ms=completed_at_ms,
            user_message=str(
                active_run.root_user_message if active_run is not None else ""
            ),
            mode=str(existing_turn.execution_mode or "function_calling"),
            run_id=(
                existing_turn.run_id
                or (active_run.run_id if active_run is not None else None)
            ),
            run_revision=existing_turn.run_revision
            or int(active_run.revision if active_run is not None else 0),
            error_summary=cancellation_reason,
        )
        return True

    async def request_session_detach(
        self,
        *,
        session_id: str,
        requested_by: str,
        reason: str = "user_detach",
        anchor_turn_id: str | None = None,
    ) -> dict[str, object] | None:
        """Request background handoff for the active session run."""

        async with self._chat_execution_admission_boundary():
            active_run = self._session_run_coordinator.request_detach(
                session_id=session_id,
                requested_by=requested_by,
                reason=reason,
            )
            if active_run is None:
                return None
        await self._postprocess_service.emit_execution_control_notification(
            user_id=self.agent_id,
            session_id=session_id,
            turn_id=anchor_turn_id or active_run.root_turn_id,
            run_id=active_run.run_id,
            state="detaching",
            can_cancel=False,
            label="Moving run to background",
        )
        return {
            "session_id": session_id,
            "run_id": active_run.run_id,
            "revision": active_run.revision,
            "status": "detaching",
            "detach_reason": reason,
            "detach_requested_by": requested_by,
            "detach_anchor_turn_id": anchor_turn_id,
        }


async def _cancel_child_runs(
    *,
    session_id: str,
    run_id: str,
    run_revision: int,
    strict: bool,
) -> list[str]:
    """Cancel child runs still owned by a foreground parent run."""

    try:
        from magi.tools.registry import tool_registry

        agent_tool = tool_registry.get_tool("agent")
        coordinator = getattr(agent_tool, "_manager", None)
        cancel_children = getattr(coordinator, "cancel_run_workers", None)
        if not callable(cancel_children):
            return []
        return await cancel_children(
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            reason="session_run_cancelled",
            include_transferred=strict,
        )
    except Exception as exc:
        logger.warning(
            "Failed to cancel child runs",
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            error=str(exc),
        )
        if strict:
            raise RuntimeError(
                "Failed to cancel child runs before destructive clear"
            ) from exc
        return []


async def _cancel_owned_run_plan(
    *,
    session_id: str,
    run_id: str,
) -> None:
    """Cancel the current run's plan."""
    try:
        from magi.control.provider import resolve_control_session_store

        store = resolve_control_session_store()
        current = store.current_run_plan(session_id, run_id=run_id)
        if current is None or current.status.value in {"completed", "cancelled"}:
            return
        await store.mutate_run_plan(
            session_id,
            run_id=run_id,
            plan_id=current.plan_id,
            expected_version=current.version,
            status="cancelled",
        )
    except Exception:
        logger.debug("run_plan.cancel_failed", exc_info=True)
