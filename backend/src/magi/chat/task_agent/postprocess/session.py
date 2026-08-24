"""Session-run completion helpers for chat post-processing."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Protocol, cast

from magi.agent.trace import now_wall_ms
from magi.core.logger import get_logger
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext

logger = get_logger(__name__)

_PENDING_INPUT_RELEASE_RETRY_INITIAL_SECONDS = 0.1
_PENDING_INPUT_RELEASE_RETRY_MAX_SECONDS = 5.0


class _SessionPostprocessHostProtocol(Protocol):
    _complete_session_run: Callable[[str, str, int], Any] | None
    _resolve_session_run_status: Callable[[str, str, int], Any] | None
    _release_pending_inputs: Callable[[str, list[Any]], Any] | None
    _unified_memory: Any
    _chat_store: Any
    _background_tasks: set[asyncio.Task[Any]]
    _pending_input_release_retry_keys: set[tuple[str, str, int]]

    async def mark_user_turn_delivery_terminal_if_persisted(
        self,
        *,
        turn_id: str | None,
        source_fact: Any,
        required_message_kind: str | None = None,
        expected_message_count: int = 0,
    ) -> bool: ...

    async def emit_execution_control_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        run_id: str | None = None,
        state: str,
        can_cancel: bool = False,
        label: str | None = None,
    ) -> None: ...


class ChatPostprocessSessionMixin:
    """Finalize chat session runs and pending input release."""

    async def _finalize_session_run(self, context: ChatRuntimeContext) -> None:
        host = cast(_SessionPostprocessHostProtocol, self)
        if host._complete_session_run is None:
            return
        run_id = str(context.session_run_id or "").strip()
        if not run_id:
            return
        revision = int(context.session_run_revision or 0)
        status = await self._session_run_status(context)
        if host._resolve_session_run_status is not None and status is None:
            return
        cancellation_turn_id: str | None = None
        if status in {"cancelling", "cancelled"}:
            active_run = context.active_run
            cancellation_turn_id = (
                str(
                    (
                        active_run.cancel_anchor_turn_id
                        if active_run is not None
                        else None
                    )
                    or (
                        active_run.root_turn_id
                        if active_run is not None
                        else None
                    )
                    or getattr(context.latest_payload, "turn_id", None)
                    or ""
                ).strip()
                or None
            )
            cancellation_committed = await self._mark_cancelled_turn(context)
            if cancellation_committed:
                await host.mark_user_turn_delivery_terminal_if_persisted(
                    turn_id=cancellation_turn_id,
                    source_fact=context.latest_fact,
                )
            else:
                status = "completed"
        try:
            completion = host._complete_session_run(
                context.session_id,
                run_id,
                revision,
            )
            if inspect.isawaitable(completion):
                completion = await completion
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to complete chat session run",
                session_id=context.session_id,
                run_id=run_id,
                revision=revision,
                error=str(exc),
            )
            raise
        completed, pending_inputs = self._normalize_run_completion(completion)
        if not completed:
            return
        if status in {"cancelling", "cancelled"}:
            active_run = context.active_run
            await host.emit_execution_control_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=cancellation_turn_id,
                run_id=run_id,
                state="cancelled",
                can_cancel=False,
                label="Run cancelled",
            )
        await self.release_pending_inputs_after_run_completion(
            session_id=context.session_id,
            run_id=run_id,
            revision=revision,
            pending_inputs=pending_inputs,
        )
        await self._notify_memory_session_end(context.session_id)

    @staticmethod
    def _normalize_run_completion(
        completion: Any,
    ) -> tuple[bool, list[Any]]:
        """Normalize the completion callback's result."""

        if isinstance(completion, tuple) and len(completion) == 2:
            completed, pending_inputs = completion
            return bool(completed), list(pending_inputs or [])
        return completion is not False, []

    async def _mark_cancelled_turn(self, context: ChatRuntimeContext) -> bool:
        host = cast(_SessionPostprocessHostProtocol, self)
        if host._chat_store is None:
            return True
        active_run = context.active_run
        turn_id = str(
            (active_run.cancel_anchor_turn_id if active_run is not None else None)
            or (active_run.root_turn_id if active_run is not None else None)
            or getattr(context.latest_payload, "turn_id", None)
            or ""
        ).strip()
        if not turn_id:
            return True
        existing_turn = await host._chat_store.get_turn(turn_id)
        if existing_turn is None:
            return True
        if str(existing_turn.status or "").strip().lower() == "cancelled":
            return True
        completed_at_ms = now_wall_ms()
        cancellation_reason = (
            str(active_run.cancel_reason or "").strip()
            if active_run is not None
            else ""
        )
        cancelled = await host._chat_store.cancel_user_turn_delivery_if_active(
            turn_id=existing_turn.turn_id,
            run_id=existing_turn.run_id or context.session_run_id,
            run_revision=(
                existing_turn.run_revision
                or int(context.session_run_revision or 0)
            ),
            reason=cancellation_reason or "user_cancel",
            updated_at_ms=completed_at_ms,
        )
        if not cancelled:
            current_turn = await host._chat_store.get_turn(turn_id)
            return bool(
                current_turn is not None
                and str(current_turn.status or "").strip().lower() == "cancelled"
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
                mode=str(existing_turn.execution_mode or "agent_run"),
                run_id=existing_turn.run_id or context.session_run_id,
                run_revision=existing_turn.run_revision
                or int(context.session_run_revision or 0),
                error_summary=existing_turn.error_text
                or (active_run.cancel_reason if active_run is not None else None),
            )
        return True

    async def _release_pending_user_inputs(
        self,
        *,
        session_id: str,
        pending_inputs: list[Any],
    ) -> bool:
        """Release unconsumed run inputs after durable run completion."""

        host = cast(_SessionPostprocessHostProtocol, self)
        if not pending_inputs:
            return True
        normalized_session_id = str(session_id or "").strip()
        if host._release_pending_inputs is None or not normalized_session_id:
            return False
        try:
            result = host._release_pending_inputs(
                normalized_session_id,
                pending_inputs,
            )
            if inspect.isawaitable(result):
                await result
            return True
        except Exception as exc:
            logger.warning(
                "Failed to release pending user inputs",
                session_id=normalized_session_id,
                error=str(exc),
            )
            return False

    async def release_pending_inputs_after_run_completion(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        pending_inputs: list[Any],
    ) -> bool:
        """Release a completed run's unconsumed inputs through the durable ledger."""

        host = cast(_SessionPostprocessHostProtocol, self)
        normalized_session_id = str(session_id or "").strip()
        normalized_run_id = str(run_id or "").strip()
        if not normalized_session_id or not normalized_run_id:
            return False

        captured_turns = list(pending_inputs)
        key = (normalized_session_id, normalized_run_id, int(revision))
        if key in host._pending_input_release_retry_keys:
            return False
        host._pending_input_release_retry_keys.add(key)

        try:
            if await self._release_pending_user_inputs(
                session_id=normalized_session_id,
                pending_inputs=captured_turns,
            ):
                host._pending_input_release_retry_keys.discard(key)
                return True
        except asyncio.CancelledError:
            host._pending_input_release_retry_keys.discard(key)
            raise

        try:
            self._schedule_pending_input_release_retry(
                session_id=normalized_session_id,
                run_id=normalized_run_id,
                revision=revision,
                pending_inputs=captured_turns,
            )
        except Exception:
            host._pending_input_release_retry_keys.discard(key)
            raise
        return False

    def _schedule_pending_input_release_retry(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        pending_inputs: list[Any],
    ) -> None:
        """Retry one unconsumed input batch without releasing it twice."""

        host = cast(_SessionPostprocessHostProtocol, self)
        key = (session_id, run_id, int(revision))
        captured_turns = list(pending_inputs)

        async def _runner() -> None:
            delay_seconds = _PENDING_INPUT_RELEASE_RETRY_INITIAL_SECONDS
            try:
                while True:
                    await asyncio.sleep(max(0.0, delay_seconds))
                    if await self._release_pending_user_inputs(
                        session_id=session_id,
                        pending_inputs=captured_turns,
                    ):
                        return
                    delay_seconds = min(
                        max(
                            _PENDING_INPUT_RELEASE_RETRY_INITIAL_SECONDS,
                            delay_seconds * 2,
                        ),
                        _PENDING_INPUT_RELEASE_RETRY_MAX_SECONDS,
                    )
            finally:
                host._pending_input_release_retry_keys.discard(key)

        task = asyncio.create_task(
            _runner(),
            name=f"pending-input-release:{session_id}:{run_id}:{revision}",
        )
        host._background_tasks.add(task)
        task.add_done_callback(host._background_tasks.discard)

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

    async def _session_run_status(
        self,
        context: ChatRuntimeContext,
    ) -> str | None:
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
                status = await status
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to resolve chat session run status",
                session_id=context.session_id,
                run_id=run_id,
                revision=revision,
                error=str(exc),
            )
            raise
        normalized = str(status or "").strip()
        return normalized or None
