"""Runtime control helpers for chat function-calling execution."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ....agent.background.contracts import BackgroundTaskTriggerSource
from ....agent.background.dispatcher import (
    BackgroundDecisionContext,
    BackgroundDecisionSource,
)
from ....agent.cancel import CancelToken, SessionRunCancelToken, null_cancel_token
from magi.control.run_control import (
    DetachSignal,
    OrchestratorSnapshot,
    SteerInbox,
    SteerMessage,
)
from ....config.loader import get_config
from ....core.logger import get_logger
from ..common import ExecutionResult, FunctionCallingExecutionResult, FunctionCallingRequest
from .handler_helpers import serialize_ux_plan as _serialize_ux_plan

if TYPE_CHECKING:
    from magi_plugin_sdk.run_trigger import RunTrigger

logger = get_logger(__name__)


def _auto_background_dispatch_enabled() -> bool:
    """Return whether chat turns may be auto-routed to background."""
    try:
        return bool(get_config().agent.background_tasks.auto_detect_long_task)
    except Exception as exc:  # noqa: BLE001 - config failure should keep the turn foreground
        logger.warning(
            "background auto-dispatch config unavailable; staying on foreground | error=%s",
            exc,
        )
        return False


_BACKGROUND_TRIGGER_SOURCE_BY_DECISION: dict[
    BackgroundDecisionSource, BackgroundTaskTriggerSource
] = {
    BackgroundDecisionSource.PLANNER: BackgroundTaskTriggerSource.PLANNER,
    BackgroundDecisionSource.RULE: BackgroundTaskTriggerSource.RULE,
    BackgroundDecisionSource.LLM: BackgroundTaskTriggerSource.CLASSIFIER,
    BackgroundDecisionSource.FALLBACK: BackgroundTaskTriggerSource.RULE,
}


class FunctionCallingRuntimeControlMixin:
    """Background dispatch, detach handoff, steer, and cancellation helpers."""

    _deps: Any

    def _build_detached_chat_result(
        self,
        *,
        request: FunctionCallingRequest,
        step_state: Any,
        detach_signal: DetachSignal,
        current_user_message: str,
        current_turn_id: str | None,
    ) -> FunctionCallingExecutionResult:
        """Wrap a detach-triggered exit as a function-calling result."""
        payload = detach_signal.payload
        reason = payload.reason if payload is not None else "detached"
        note = payload.note if payload is not None else ""
        snapshot = OrchestratorSnapshot(
            messages=[dict(msg) for msg in step_state.messages],
            iterations=step_state.iteration,
            reason=reason,
            note=note,
        )
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text="",
            attachments=list(getattr(step_state, "chat_attachments", []) or []),
            message_payload=dict(getattr(step_state, "message_payload", {}) or {}),
            root_user_message=current_user_message,
            execution_outcome={
                "status": "detached",
                "content": "",
                "failure_reason": None,
                "attachments": list(getattr(step_state, "chat_attachments", []) or []),
                "message_payload": dict(getattr(step_state, "message_payload", {}) or {}),
                "tool_failures": list(getattr(step_state, "tool_failures", [])),
                "iterations": step_state.iteration,
                "snapshot": snapshot.to_dict(),
            },
            turn_id=current_turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )

    async def _maybe_dispatch_to_background(
        self, request: FunctionCallingRequest
    ) -> ExecutionResult | None:
        """Delegate to the background runtime when the dispatcher agrees."""
        if not _auto_background_dispatch_enabled():
            return None
        dispatcher = self._deps.background_dispatcher
        launch_service = self._deps.background_launch_service
        if dispatcher is None or launch_service is None:
            return None
        try:
            decision = await dispatcher.classify(
                BackgroundDecisionContext(
                    user_text=request.context.latest_user_message or "",
                    selected_tools=list(request.selected_tools),
                )
            )
        except Exception as exc:  # noqa: BLE001 - degrade safe to foreground
            logger.warning(
                "background dispatcher failed; staying on foreground | user_id=%s error=%s",
                request.context.user_id,
                exc,
            )
            return None
        if not decision.is_background:
            return None
        trigger_source = _BACKGROUND_TRIGGER_SOURCE_BY_DECISION.get(
            decision.source, BackgroundTaskTriggerSource.RULE
        )
        try:
            return await launch_service.enqueue_from_request(
                request, trigger_source=trigger_source
            )
        except Exception as exc:  # noqa: BLE001 - degrade safe to foreground
            logger.warning(
                "background launch failed; falling back to foreground | user_id=%s error=%s",
                request.context.user_id,
                exc,
            )
            return None

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
        self, request: FunctionCallingRequest
    ) -> SteerInbox | None:
        """Return an empty steer inbox for this turn, or ``None``."""
        coordinator = self._deps.session_run_coordinator
        session_id = str(getattr(request.context, "session_id", "") or "").strip()
        if coordinator is None or not session_id:
            return None
        return SteerInbox()

    async def _drain_pending_steer_turns(
        self,
        *,
        session_id: str,
        revision: int,
        steer_inbox: SteerInbox | None,
        step_state: Any,
        latest_fact_timestamp: float | None,
    ) -> None:
        """Pull freshly persisted STEER turns into ``steer_inbox``."""
        coordinator = self._deps.session_run_coordinator
        if coordinator is None or steer_inbox is None or not session_id:
            return
        apply_steer = getattr(
            self._deps.function_calling_orchestrator, "apply_steer_messages", None
        )
        if apply_steer is None:
            return
        drained = coordinator.consume_steer_turns(session_id, revision=revision)
        if not drained:
            await apply_steer(step_state, steer_inbox)
            return

        for pending_turn in drained:
            await steer_inbox.push(
                SteerMessage(
                    content=pending_turn.content,
                    reason="steer",
                    metadata={"turn_id": pending_turn.turn_id},
                )
            )
        await apply_steer(step_state, steer_inbox)

        persist = self._deps.persist_turn_supersessions
        if persist is None:
            return
        active_run = coordinator.get_active_run(session_id)
        if active_run is None:
            return
        supersessions = coordinator._build_steer_supersessions(
            root_turn_id=active_run.root_turn_id,
            pending_turns=drained,
            anchor_turn_id=drained[-1].turn_id,
        )
        if not supersessions:
            return
        updated_at_ms = (
            int(latest_fact_timestamp * 1000)
            if latest_fact_timestamp is not None
            else int(time.time() * 1000)
        )
        await persist(supersessions, updated_at_ms)

    async def _maybe_handoff_detached_outcome(
        self,
        request: FunctionCallingRequest,
        result: ExecutionResult,
    ) -> ExecutionResult | None:
        """Launch detached results in the background when possible."""
        launch_service = self._deps.background_launch_service
        if launch_service is None:
            return None
        if not isinstance(result, FunctionCallingExecutionResult):
            return None
        execution_outcome = result.execution_outcome
        if not isinstance(execution_outcome, dict):
            return None
        if execution_outcome.get("status") != "detached":
            return None
        snapshot = execution_outcome.get("snapshot")
        initial_messages: list[dict[str, Any]] | None = None
        if isinstance(snapshot, dict):
            raw_messages = snapshot.get("messages")
            if isinstance(raw_messages, list):
                initial_messages = [
                    dict(msg) for msg in raw_messages if isinstance(msg, dict)
                ]
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
                initial_messages=initial_messages,
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
        self, request: FunctionCallingRequest
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