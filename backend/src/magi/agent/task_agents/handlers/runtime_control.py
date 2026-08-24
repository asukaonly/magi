"""Runtime control helpers for chat function-calling execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....agent.background.contracts import BackgroundTaskTriggerSource
from ....agent.cancel import CancelToken, SessionRunCancelToken, null_cancel_token
from magi.control.run_control import (
    DetachSignal,
    SteerInbox,
)
from ....core.logger import get_logger
from ..common import AgentRunExecutionResult, ExecutionResult, PreparedAgentRunRequest

if TYPE_CHECKING:
    from magi_plugin_sdk.run_trigger import RunTrigger

logger = get_logger(__name__)


class FunctionCallingRuntimeControlMixin:
    """Background dispatch, detach handoff, steer, and cancellation helpers."""

    _deps: Any

    def _build_detach_signal(self, *, session_id: str = "") -> DetachSignal | None:
        """Return a fresh detach signal for this turn, or ``None``."""
        if self._deps.background_launch_service is None:
            return None
        signal = DetachSignal()
        coordinator = getattr(self._deps, "session_run_coordinator", None)
        bind_signal = getattr(coordinator, "bind_detach_signal", None)
        if coordinator is not None and callable(bind_signal) and session_id:
            bind_signal(session_id, signal)
        return signal

    def _release_detach_signal(
        self,
        *,
        session_id: str,
        detach_signal: DetachSignal | None,
    ) -> None:
        coordinator = self._deps.session_run_coordinator
        release_signal = getattr(coordinator, "release_detach_signal", None)
        if coordinator is None or not callable(release_signal) or not session_id:
            return
        release_signal(session_id, detach_signal)

    async def _build_steer_inbox(
        self, request: PreparedAgentRunRequest
    ) -> SteerInbox | None:
        """Return an empty steer inbox for this turn, or ``None``."""
        coordinator = self._deps.session_run_coordinator
        session_id = str(getattr(request.context, "session_id", "") or "").strip()
        if coordinator is None or not session_id:
            return None
        return SteerInbox()

    async def _maybe_handoff_detached_outcome(
        self,
        request: PreparedAgentRunRequest,
        result: ExecutionResult,
    ) -> ExecutionResult | None:
        """Launch detached results in the background when possible."""
        launch_service = self._deps.background_launch_service
        if launch_service is None:
            return None
        if not isinstance(result, AgentRunExecutionResult):
            return None
        execution_outcome = result.execution_outcome
        if not isinstance(execution_outcome, dict):
            return None
        if execution_outcome.get("status") != "detached":
            return None
        checkpoint = execution_outcome.get("snapshot")
        if not isinstance(checkpoint, dict):
            return None
        # ADR-0004 P3: the detaching run carries a typed RunTrigger describing
        # its origin (e.g. weixin/iMessage). Hand it to the background spec so a
        # completed task can be delivered back to that channel, and derive the
        # coarse trigger_source from it instead of the blanket MANUAL.
        run_trigger = self._resolve_run_trigger(
            str(getattr(request.context, "session_id", "") or "").strip()
        )
        try:
            return await launch_service.enqueue_from_request(
                request,
                trigger_source=BackgroundTaskTriggerSource.from_trigger(run_trigger),
                trigger=run_trigger,
                agent_run_checkpoint=dict(checkpoint),
            )
        except Exception as exc:  # noqa: BLE001 - degrade safe: surface detach
            logger.warning(
                "detach hand-off failed; keeping detached outcome visible | "
                "user_id=%s error=%s",
                request.context.user_id,
                exc,
            )
            return None

    def _resolve_run_trigger(self, session_id: str) -> "RunTrigger | None":
        """Best-effort fetch of the active run's origin ``RunTrigger``.

        Returns ``None`` when no coordinator is wired, no active run exists, or
        the run predates trigger propagation — letting callers fall back to
        legacy behavior. ``getattr``-defensive so test deps that omit the
        coordinator do not raise, and never lets a provenance lookup break the
        detach hand-off.
        """
        if not session_id:
            return None
        coordinator = getattr(self._deps, "session_run_coordinator", None)
        get_active_run = getattr(coordinator, "get_active_run", None)
        if not callable(get_active_run):
            return None
        try:
            active_run = get_active_run(session_id)
        except Exception as exc:  # noqa: BLE001 - provenance is best-effort
            logger.warning(
                "active-run trigger lookup failed; detaching without trigger | "
                "session_id=%s error=%s",
                session_id,
                exc,
            )
            return None
        return getattr(active_run, "trigger", None)

    def _build_cancel_token(
        self, request: PreparedAgentRunRequest
    ) -> CancelToken:
        """Build a cancel token bound to one specific run revision."""
        coordinator = self._deps.session_run_coordinator
        session_id = str(request.context.session_id or "").strip()
        run_id = str(request.context.session_run_id or "").strip()
        if coordinator is None or not session_id or not run_id:
            return null_cancel_token()
        revision = int(getattr(request.context, "session_run_revision", 0) or 0)
        return SessionRunCancelToken(
            coordinator=coordinator,
            session_id=session_id,
            run_id=run_id,
            revision=revision,
        )


__all__ = ["FunctionCallingRuntimeControlMixin"]
