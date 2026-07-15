"""Session-run control operations for the chat task agent."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.types import TaskAgentType
from magi.agent.trace import now_wall_ms
from magi.chat import ChatTurnRecord
from magi.core.logger import get_logger

logger = get_logger(__name__)


class ChatSessionControlMixin:
    """Ingress interrupt, deferred-turn, cancel, and detach helpers."""

    _interruption_classifier: Any
    _session_run_coordinator: Any
    _task_agent_manager: Any
    _task_orchestrator: Any
    _postprocess_service: Any
    _chat_store: Any
    agent_id: str
    runtime_key: str
    agent_type: Any

    async def _request_ingress_interrupt(self, fact: FactRecord) -> None:
        """Best-effort strict interrupt handling before the fact queue drains."""
        try:
            from magi.events.events import EventTypes

            if fact.event_type != EventTypes.USER_MESSAGE:
                return
            payload = fact.payload or {}
            session_id = str(payload.get("session_id") or "").strip()
            content = str(payload.get("content") or "")
            turn_id = str(payload.get("turn_id") or "").strip() or None
            if not (
                session_id
                and content
                and self._interruption_classifier.looks_like_strict_interrupt(content)
            ):
                return
            active_run = self._session_run_coordinator.get_active_run(session_id)
            if active_run is None or active_run.status not in ("running", "cancelling"):
                return
            self._session_run_coordinator.request_cancel(
                session_id=session_id,
                requested_by="user",
                reason="ingress_interrupt",
                anchor_turn_id=turn_id,
            )
            logger.info(
                "Ingress INTERRUPT detected; requested cancel",
                session_id=session_id,
                turn_id=turn_id,
            )
        except Exception as exc:
            logger.debug(
                "Ingress INTERRUPT classification failed",
                error=str(exc),
            )

    async def _drain_deferred_turns(self, session_id: str) -> None:
        """Re-inject queued DEFER user turns as fresh user-message facts."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        manager = self._task_agent_manager
        if manager is None:
            return
        try:
            deferred_turns = self._session_run_coordinator.consume_deferred_turns(
                normalized_session_id
            )
        except ValueError:
            return
        if not deferred_turns:
            return
        from magi.events.events import EventTypes

        for pending_turn in deferred_turns:
            reinjected_turn_id = uuid4().hex
            payload: dict[str, object] = {
                "session_id": normalized_session_id,
                "user_id": self.agent_id,
                "turn_id": reinjected_turn_id,
                "content": pending_turn.content,
                "author_type": "user",
                "content_type": "text",
                "timestamp": pending_turn.created_at,
                "metadata": {
                    "reinjected_from": "deferred_pending_turn",
                    "source_turn_id": pending_turn.turn_id,
                },
            }
            fact = FactRecord(
                agent_id=self.runtime_key,
                agent_type=str(
                    self.agent_type.value
                    if hasattr(self.agent_type, "value")
                    else self.agent_type
                ),
                agent_instance_id=normalized_session_id,
                event_type=EventTypes.USER_MESSAGE,
                payload=payload,
                correlation_id=reinjected_turn_id,
                user_message_generation=(
                    manager.current_user_message_generation()
                    if callable(
                        getattr(manager, "current_user_message_generation", None)
                    )
                    else None
                ),
            )
            try:
                await manager.add_fact_to_agent(
                    TaskAgentType.CHAT,
                    normalized_session_id,
                    fact,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to reinject deferred user turn",
                    session_id=normalized_session_id,
                    turn_id=reinjected_turn_id,
                    source_turn_id=pending_turn.turn_id,
                    error=str(exc),
                )

    async def request_session_cancel(
        self,
        *,
        session_id: str,
        requested_by: str,
        reason: str = "user_cancel",
        anchor_turn_id: str | None = None,
    ) -> dict[str, object] | None:
        """Request strong cancellation for the active session run."""
        active_run = self._session_run_coordinator.request_cancel(
            session_id=session_id,
            requested_by=requested_by,
            reason=reason,
            anchor_turn_id=anchor_turn_id,
        )
        if active_run is None:
            return None
        cancelled_orchestration_ids = await self._task_orchestrator.cancel_run(
            session_id=session_id,
            run_id=active_run.run_id,
            run_revision=active_run.revision,
            strict_worker_cancellation=reason == "memory_clear",
        )
        self._session_run_coordinator.complete_run(
            session_id=session_id,
            run_id=active_run.run_id,
            revision=active_run.revision,
        )
        await self._mark_session_turn_cancelled(active_run)
        await self._postprocess_service.emit_execution_control_notification(
            user_id=self.agent_id,
            session_id=session_id,
            turn_id=active_run.cancel_anchor_turn_id or active_run.root_turn_id,
            run_id=active_run.run_id,
            orchestration_id=(
                cancelled_orchestration_ids[0] if cancelled_orchestration_ids else None
            ),
            state="cancelled",
            can_cancel=False,
            label="Run cancelled",
        )
        current_run = (
            self._session_run_coordinator.get_active_run(session_id) or active_run
        )
        return {
            "session_id": session_id,
            "run_id": current_run.run_id,
            "revision": current_run.revision,
            "status": current_run.status,
            "cancel_reason": current_run.cancel_reason,
            "cancel_requested_by": current_run.cancel_requested_by,
            "cancel_anchor_turn_id": current_run.cancel_anchor_turn_id,
            "cancelled_orchestration_ids": cancelled_orchestration_ids,
        }

    async def _mark_session_turn_cancelled(self, active_run: Any) -> None:
        chat_store = getattr(self, "_chat_store", None)
        if chat_store is None:
            return
        turn_id = str(
            getattr(active_run, "cancel_anchor_turn_id", None)
            or getattr(active_run, "root_turn_id", None)
            or ""
        ).strip()
        if not turn_id:
            return
        existing_turn = await chat_store.get_turn(turn_id)
        if existing_turn is None:
            return
        completed_at_ms = now_wall_ms()
        await chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id,
                orchestration_id=existing_turn.orchestration_id,
                status="cancelled",
                response_mode=existing_turn.response_mode,
                execution_mode=existing_turn.execution_mode,
                ux_plan_json=existing_turn.ux_plan_json,
                created_at_ms=existing_turn.created_at_ms,
                updated_at_ms=completed_at_ms,
                completed_at_ms=completed_at_ms,
                error_text=existing_turn.error_text
                or getattr(active_run, "cancel_reason", None),
                run_id=existing_turn.run_id or getattr(active_run, "run_id", None),
                run_revision=existing_turn.run_revision
                or int(getattr(active_run, "revision", 0) or 0),
                run_disposition=existing_turn.run_disposition,
                response_anchor_turn_id=existing_turn.response_anchor_turn_id,
                superseded_by_turn_id=existing_turn.superseded_by_turn_id,
                supersession_reason=existing_turn.supersession_reason,
            )
        )
        emit_cancelled_turn_trace = getattr(
            self._postprocess_service,
            "emit_cancelled_turn_trace",
            None,
        )
        if callable(emit_cancelled_turn_trace):
            await emit_cancelled_turn_trace(
                user_id=existing_turn.user_id,
                session_id=existing_turn.session_id,
                turn_id=existing_turn.turn_id,
                started_at_ms=existing_turn.created_at_ms,
                cancelled_at_ms=completed_at_ms,
                user_message=str(getattr(active_run, "root_user_message", "") or ""),
                mode=str(existing_turn.execution_mode or "function_calling"),
                run_id=existing_turn.run_id or getattr(active_run, "run_id", None),
                run_revision=existing_turn.run_revision
                or int(getattr(active_run, "revision", 0) or 0),
                error_summary=getattr(active_run, "cancel_reason", None),
            )

    async def request_session_detach(
        self,
        *,
        session_id: str,
        requested_by: str,
        reason: str = "user_detach",
        anchor_turn_id: str | None = None,
    ) -> dict[str, object] | None:
        """Request background handoff for the active session run."""
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
            orchestration_id=None,
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
