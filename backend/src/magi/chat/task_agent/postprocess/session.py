"""Session-run completion helpers for chat post-processing."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Protocol, cast

from magi.agent.trace import now_wall_ms
from magi.chat import ChatTurnRecord
from magi.core.logger import get_logger
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext

logger = get_logger(__name__)


class _SessionPostprocessHostProtocol(Protocol):
    _complete_session_run: Callable[[str, str, int], Any] | None
    _resolve_session_run_status: Callable[[str, str, int], Any] | None
    _drain_deferred_turns: Callable[[str], Any] | None
    _unified_memory: Any
    _chat_store: Any

    async def emit_execution_control_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        run_id: str | None = None,
        orchestration_id: str | None = None,
        state: str,
        can_cancel: bool = False,
        label: str | None = None,
    ) -> None: ...


class ChatPostprocessSessionMixin:
    """Finalize chat session runs and deferred turn side effects."""

    async def _finalize_session_run(self, context: ChatRuntimeContext) -> None:
        host = cast(_SessionPostprocessHostProtocol, self)
        if host._complete_session_run is None:
            return
        run_id = str(context.session_run_id or "").strip()
        if not run_id:
            return
        revision = int(context.session_run_revision or 0)
        try:
            completion = host._complete_session_run(
                context.session_id,
                run_id,
                revision,
            )
            if inspect.isawaitable(completion):
                await completion
        except Exception as exc:
            logger.warning(
                "Failed to complete chat session run",
                session_id=context.session_id,
                run_id=run_id,
                revision=revision,
                error=str(exc),
            )
            return
        status = self._session_run_status(context)
        if status == "cancelled":
            active_run = context.active_run
            await self._mark_cancelled_turn(context)
            await host.emit_execution_control_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=(
                    str(
                        (
                            active_run.cancel_anchor_turn_id
                            if active_run is not None
                            else None
                        )
                        or ""
                    ).strip()
                    or str(
                        (active_run.root_turn_id if active_run is not None else None)
                        or ""
                    ).strip()
                    or None
                ),
                run_id=run_id,
                orchestration_id=(
                    str(
                        context.active_orchestrations[0].get("orchestration_id") or ""
                    ).strip()
                    if context.active_orchestrations
                    and isinstance(context.active_orchestrations[0], dict)
                    else None
                ),
                state="cancelled",
                can_cancel=False,
                label="Run cancelled",
            )
        await self._drain_deferred_user_turns(context)
        await self._notify_memory_session_end(context.session_id)

    async def _mark_cancelled_turn(self, context: ChatRuntimeContext) -> None:
        host = cast(_SessionPostprocessHostProtocol, self)
        if host._chat_store is None:
            return
        active_run = context.active_run
        turn_id = str(
            (active_run.cancel_anchor_turn_id if active_run is not None else None)
            or (active_run.root_turn_id if active_run is not None else None)
            or getattr(context.latest_payload, "turn_id", None)
            or ""
        ).strip()
        if not turn_id:
            return
        existing_turn = await host._chat_store.get_turn(turn_id)
        if existing_turn is None:
            return
        completed_at_ms = now_wall_ms()
        await host._chat_store.upsert_turn(
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
                or (active_run.cancel_reason if active_run is not None else None),
                run_id=existing_turn.run_id or context.session_run_id,
                run_revision=existing_turn.run_revision
                or int(context.session_run_revision or 0),
                run_disposition=existing_turn.run_disposition,
                response_anchor_turn_id=existing_turn.response_anchor_turn_id,
                superseded_by_turn_id=existing_turn.superseded_by_turn_id,
                supersession_reason=existing_turn.supersession_reason,
            )
        )
        emit_cancelled_turn_trace = getattr(self, "emit_cancelled_turn_trace", None)
        if callable(emit_cancelled_turn_trace):
            await emit_cancelled_turn_trace(
                user_id=existing_turn.user_id,
                session_id=existing_turn.session_id,
                turn_id=existing_turn.turn_id,
                started_at_ms=existing_turn.created_at_ms,
                cancelled_at_ms=completed_at_ms,
                user_message=(
                    str(
                        active_run.root_user_message
                        or context.latest_user_message
                        or ""
                    )
                    if active_run is not None
                    else str(context.latest_user_message or "")
                ),
                mode=str(existing_turn.execution_mode or "function_calling"),
                run_id=existing_turn.run_id or context.session_run_id,
                run_revision=existing_turn.run_revision
                or int(context.session_run_revision or 0),
                error_summary=existing_turn.error_text
                or (active_run.cancel_reason if active_run is not None else None),
            )

    async def _drain_deferred_user_turns(self, context: ChatRuntimeContext) -> None:
        """Re-inject DEFER pending turns after active run finalization."""
        host = cast(_SessionPostprocessHostProtocol, self)
        if host._drain_deferred_turns is None:
            return
        session_id = str(context.session_id or "").strip()
        if not session_id:
            return
        try:
            result = host._drain_deferred_turns(session_id)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "Failed to drain deferred user turns",
                session_id=session_id,
                error=str(exc),
            )

    async def _notify_memory_session_end(self, session_id: str | None) -> None:
        """Notify L2 that a chat session ended so it can flush staged memory."""
        host = cast(_SessionPostprocessHostProtocol, self)
        if not session_id or host._unified_memory is None:
            return
        on_session_end = getattr(host._unified_memory, "on_session_end", None)
        if on_session_end is None:
            return
        try:
            await on_session_end(session_id)
        except Exception:
            logger.warning(
                "L2 session-end review failed",
                session_id=session_id,
                exc_info=True,
            )

    def _session_run_status(self, context: ChatRuntimeContext) -> str | None:
        host = cast(_SessionPostprocessHostProtocol, self)
        if host._resolve_session_run_status is None:
            return None
        run_id = str(context.session_run_id or "").strip()
        if not run_id:
            return None
        revision = int(context.session_run_revision or 0)
        try:
            status = host._resolve_session_run_status(
                context.session_id,
                run_id,
                revision,
            )
            if inspect.isawaitable(status):
                return None
        except Exception as exc:
            logger.warning(
                "Failed to resolve chat session run status",
                session_id=context.session_id,
                run_id=run_id,
                revision=revision,
                error=str(exc),
            )
            return None
        normalized = str(status or "").strip()
        return normalized or None
