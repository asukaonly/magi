"""Active-run detach and pending-input deletion helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from magi.control.run_control import DetachRequested, DetachSignal
from magi.agent.task_agents.handlers.run_contracts import AgentRun, PendingTurn

if TYPE_CHECKING:
    from .run_store import SessionRunStore


class SessionRunTurnQueueMixin:
    """Control helpers for :class:`SessionRunCoordinator`."""

    _run_store: "SessionRunStore"
    _detach_signals: dict[str, DetachSignal]

    def bind_detach_signal(self, session_id: str, signal: DetachSignal) -> None:
        """Expose the active run's detach signal for out-of-band user requests."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        self._detach_signals[normalized_session_id] = signal

    def release_detach_signal(
        self,
        session_id: str,
        signal: DetachSignal | None = None,
    ) -> None:
        """Drop the registered detach signal once the foreground run exits."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        current = self._detach_signals.get(normalized_session_id)
        if current is None:
            return
        if signal is not None and current is not signal:
            return
        self._detach_signals.pop(normalized_session_id, None)

    def request_detach(
        self,
        session_id: str,
        *,
        requested_by: str,
        reason: str = "user_detach",
        note: str = "",
    ) -> AgentRun | None:
        """Request that the active run detach to background at the next boundary."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return None
        active_run = self._run_store.get_active_run(normalized_session_id)
        signal = self._detach_signals.get(normalized_session_id)
        if active_run is None or signal is None or active_run.status != "running":
            return None
        if not signal.is_requested():
            signal.request(
                DetachRequested(
                    reason=reason,
                    requested_by=requested_by,
                    note=note,
                )
            )
        return active_run

    async def discard_pending_turn_for_message_delete(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str | None,
        revision: int | None,
    ) -> PendingTurn | None:
        """Detach one exact unconsumed user turn from its active root run."""

        return await self._run_store.discard_pending_turn_for_delete(
            session_id,
            turn_id=turn_id,
            run_id=run_id,
            revision=revision,
        )
