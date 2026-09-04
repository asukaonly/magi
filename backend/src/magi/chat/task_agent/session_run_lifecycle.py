"""Active-run lifecycle and result-barrier helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from magi.agent.runtime.contracts import FactRecord
from magi.control.run_control import RunControl
from magi.control.cancel import SessionRunCancelToken
from magi.agent.task_agents.common import UserMessagePayload
from .fact_classifier import ClassifiedFact
from magi.agent.task_agents.handlers.run_contracts import (
    AgentRun,
    PendingTurn,
    RunResult,
)

if TYPE_CHECKING:
    from .run_store import SessionRunStore


class SessionRunLifecycleMixin:
    """Lifecycle operations used by :class:`SessionRunCoordinator`."""

    _run_store: "SessionRunStore"

    def get_active_run(self, session_id: str) -> AgentRun | None:
        """Return the current active run for one session."""
        return self._run_store.get_active_run(session_id)

    def get_run_status(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> str | None:
        """Return the current status for the requested session run."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return None
        if run_id is not None and active_run.run_id != run_id:
            return None
        if revision is not None and active_run.revision != int(revision):
            return None
        return active_run.status

    def request_cancel(
        self,
        *,
        session_id: str,
        requested_by: str,
        reason: str = "user_cancel",
        anchor_turn_id: str | None = None,
    ) -> AgentRun | None:
        """Mark the active run as cancelling when one exists."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return None
        cancelling_run = self._run_store.request_cancel(
            session_id,
            requested_by=requested_by,
            reason=reason,
            anchor_turn_id=anchor_turn_id,
        )
        control = self._run_store.get_active_run_control(
            session_id,
            cancelling_run.run_id,
        )
        if control is not None and isinstance(
            control.cancel_token,
            SessionRunCancelToken,
        ):
            control.cancel_token.cancel(reason)
        return cancelling_run

    def record_result(
        self,
        *,
        session_id: str,
        run_id: str,
        result_id: str,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Apply revision barriers to one internal result."""
        return self._run_store.record_result(
            session_id=session_id,
            run_id=run_id,
            result_id=result_id,
            revision=revision,
            payload=payload,
        )

    def complete_run(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> bool:
        """Complete the active run if it still matches the expected identity."""
        completed, _ = self.complete_run_with_pending_inputs(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        )
        return completed

    def complete_run_with_pending_inputs(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> tuple[bool, list[PendingTurn]]:
        """Complete one exact run and atomically detach unconsumed inputs."""

        return self._run_store.complete_active_run_with_pending_inputs(
            session_id,
            run_id=run_id,
            revision=revision,
        )

    def register_active_run_control(
        self,
        session_id: str,
        run_id: str,
        control: RunControl,
    ) -> None:
        """Proxy to ``SessionRunStore.register_active_run_control``."""
        self._run_store.register_active_run_control(session_id, run_id, control)

    def get_active_run_control(
        self,
        session_id: str,
        run_id: str,
    ) -> "RunControl | None":
        """Proxy to ``SessionRunStore.get_active_run_control``."""
        return self._run_store.get_active_run_control(session_id, run_id)

    def unregister_active_run_control(
        self,
        session_id: str,
        run_id: str,
    ) -> None:
        """Proxy to ``SessionRunStore.unregister_active_run_control``."""
        self._run_store.unregister_active_run_control(session_id, run_id)

    def _record_classified_result(
        self,
        *,
        classified_fact: ClassifiedFact,
        active_run: AgentRun | None,
    ) -> RunResult | None:
        result_fact = classified_fact.latest_result_fact
        if active_run is None or not isinstance(result_fact, FactRecord):
            return None
        if not isinstance(result_fact.payload, dict):
            return None
        run_id = str(result_fact.payload.get("run_id") or "").strip()
        if not run_id:
            return None
        try:
            revision = int(result_fact.payload.get("run_revision"))
        except (TypeError, ValueError):
            return None
        result_id = str(result_fact.correlation_id or result_fact.event_id or uuid4().hex)
        return self.record_result(
            session_id=classified_fact.session_id,
            run_id=run_id,
            result_id=result_id,
            revision=revision,
            payload=dict(result_fact.payload),
        )

    def _resolve_turn_id(
        self,
        *,
        payload: UserMessagePayload,
        source_fact: FactRecord | None,
    ) -> str:
        if payload.turn_id:
            return payload.turn_id
        if isinstance(source_fact, FactRecord) and source_fact.correlation_id:
            return source_fact.correlation_id
        return uuid4().hex
