"""Session-run control operations for the chat task agent."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ....agent.runtime.contracts import FactRecord
from ....agent.runtime.types import TaskAgentType
from ....core.logger import get_logger

logger = get_logger(__name__)


class ChatSessionControlMixin:
    """Ingress interrupt, deferred-turn, cancel, and detach helpers."""

    _interruption_classifier: Any
    _session_run_coordinator: Any
    _task_agent_manager: Any
    _task_orchestrator: Any
    _postprocess_service: Any
    agent_id: str
    runtime_key: str
    agent_type: Any

    async def _request_ingress_interrupt(self, fact: FactRecord) -> None:
        """Best-effort strict interrupt handling before the fact queue drains."""
        try:
            from ....events.events import EventTypes

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
        from ....events.events import EventTypes

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
                agent_type=str(self.agent_type.value if hasattr(self.agent_type, "value") else self.agent_type),
                agent_instance_id=normalized_session_id,
                event_type=EventTypes.USER_MESSAGE,
                payload=payload,
                correlation_id=reinjected_turn_id,
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
        )
        await self._postprocess_service.emit_execution_control_notification(
            user_id=self.agent_id,
            session_id=session_id,
            turn_id=active_run.cancel_anchor_turn_id or active_run.root_turn_id,
            run_id=active_run.run_id,
            orchestration_id=(cancelled_orchestration_ids[0] if cancelled_orchestration_ids else None),
            state="cancelling",
            can_cancel=False,
            label="Cancelling run",
        )
        return {
            "session_id": session_id,
            "run_id": active_run.run_id,
            "revision": active_run.revision,
            "status": active_run.status,
            "cancel_reason": active_run.cancel_reason,
            "cancel_requested_by": active_run.cancel_requested_by,
            "cancel_anchor_turn_id": active_run.cancel_anchor_turn_id,
            "cancelled_orchestration_ids": cancelled_orchestration_ids,
        }

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