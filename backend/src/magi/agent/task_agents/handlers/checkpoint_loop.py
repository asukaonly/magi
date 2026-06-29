"""Checkpointed function-calling loop for chat execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ....agent.cancel import CancelToken
from ....agent.turn_input import UserTurnInput
from magi.control.run_control import (
    DetachSignal,
    SteerInbox,
    bind_detach_signal,
    null_run_control,
)
from ...run.ports import AttachmentResolverPort
from ..common import FunctionCallingExecutionResult, FunctionCallingRequest
from .attachment_context import resolve_effective_turn_attachments
from .handler_helpers import serialize_ux_plan as _serialize_ux_plan


@dataclass(slots=True)
class _LoopCursor:
    """Mutable cursor for a checkpointed tool loop run."""

    user_message: str
    revision: int
    turn_id: str | None
    step_state: Any


class FunctionCallingCheckpointLoop:
    """Run the checkpoint-aware function-calling loop for one chat turn."""

    def __init__(
        self,
        *,
        deps: Any,
        attachment_resolver: AttachmentResolverPort,
        cancel_token_factory: Callable[[FunctionCallingRequest], CancelToken],
        detached_result_builder: Callable[..., FunctionCallingExecutionResult],
        drain_pending_steer_turns: Callable[..., Awaitable[None]],
    ) -> None:
        self._deps = deps
        self._attachment_resolver = attachment_resolver
        self._cancel_token_factory = cancel_token_factory
        self._detached_result_builder = detached_result_builder
        self._drain_pending_steer_turns = drain_pending_steer_turns

    async def run(
        self,
        request: FunctionCallingRequest,
        *,
        execution_workspace: str | None,
        detach_signal: DetachSignal | None = None,
        steer_inbox: SteerInbox | None = None,
    ) -> FunctionCallingExecutionResult:
        orchestrator = self._deps.function_calling_orchestrator
        cursor = self._initial_cursor(request)
        cancel_token = self._cancel_token_factory(request)
        max_iterations = int(getattr(orchestrator, "MAX_ITERATIONS", 10) or 10)

        with bind_detach_signal(detach_signal):
            while cursor.step_state.iteration < max_iterations:
                cancelled = await self._maybe_build_cancelled_result(
                    request=request,
                    cursor=cursor,
                    cancel_token=cancel_token,
                    include_payload=True,
                )
                if cancelled is not None:
                    return cancelled

                detached = self._build_detached_result_if_requested(
                    request=request,
                    cursor=cursor,
                    detach_signal=detach_signal,
                )
                if detached is not None:
                    return detached

                await self._drain_pending_steer_turns(
                    session_id=request.context.session_id,
                    revision=cursor.revision,
                    steer_inbox=steer_inbox,
                    step_state=cursor.step_state,
                    latest_fact_timestamp=getattr(
                        request.context.latest_payload, "timestamp", None
                    ),
                )

                step_outcome = await self._execute_step(
                    request=request,
                    cursor=cursor,
                    execution_workspace=execution_workspace,
                    cancel_token=cancel_token,
                )
                step_result = self._build_step_terminal_result(
                    request=request,
                    cursor=cursor,
                    step_outcome=step_outcome,
                )
                if step_result is not None:
                    return step_result
                if step_outcome.status == "failed":
                    break

                detached = self._build_detached_result_if_requested(
                    request=request,
                    cursor=cursor,
                    detach_signal=detach_signal,
                )
                if detached is not None:
                    return detached

                if await self._rebuild_from_active_run_if_needed(
                    request=request,
                    cursor=cursor,
                    steer_inbox=steer_inbox,
                ):
                    continue

                if self._rebuild_from_checkpoint_if_needed(
                    request=request,
                    cursor=cursor,
                ):
                    continue

            return await self._run_fallback(
                request=request,
                cursor=cursor,
                execution_workspace=execution_workspace,
                cancel_token=cancel_token,
            )

    def _initial_cursor(self, request: FunctionCallingRequest) -> _LoopCursor:
        user_message = request.context.latest_user_message
        return _LoopCursor(
            user_message=user_message,
            revision=int(getattr(request.context, "session_run_revision", 0) or 0),
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
            step_state=self._build_step_state(request, user_message),
        )

    def _build_step_state(
        self,
        request: FunctionCallingRequest,
        user_message: str,
    ) -> Any:
        return self._deps.function_calling_orchestrator.build_step_state(
            turn=UserTurnInput(
                text=user_message,
                attachments=resolve_effective_turn_attachments(
                    request.context, resolver=self._attachment_resolver
                ),
                user_id=request.context.user_id,
                session_id=request.context.session_id,
            ),
            system_prompt=request.system_prompt,
            selected_tools=request.selected_tools,
            conversation_history=request.context.history,
            session_summary=getattr(request.context, "session_summary", None),
            session_origin=getattr(request.context, "session_origin", None),
            reply_context=getattr(request.context, "reply_context", None),
            allow_attachment_grounding=self._allow_attachment_grounding(request),
        )

    @staticmethod
    def _allow_attachment_grounding(request: FunctionCallingRequest) -> bool:
        return bool(
            getattr(request.context, "allow_media_grounding_for_conversation", False)
        ) and bool(getattr(request.context, "core_model_supports_vision", False))

    async def _execute_step(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        execution_workspace: str | None,
        cancel_token: CancelToken,
    ) -> Any:
        return await self._deps.function_calling_orchestrator.step_executor.execute_step(
            state=cursor.step_state,
            user_message=cursor.user_message,
            thinking_depth=request.thinking_depth,
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            session_run_id=request.context.session_run_id,
            session_run_revision=cursor.revision,
            turn_id=cursor.turn_id,
            intent=request.intent.intent,
            execution_agent_id=request.context.runtime_key,
            execution_workspace=execution_workspace,
            cancel_token=cancel_token,
            route_decision=request.intent.route_decision,
        )

    async def _maybe_build_cancelled_result(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        cancel_token: CancelToken,
        include_payload: bool,
    ) -> FunctionCallingExecutionResult | None:
        if not await cancel_token.is_cancelled():
            return None
        return self._build_cancelled_result(
            request=request,
            cursor=cursor,
            include_payload=include_payload,
        )

    def _build_step_terminal_result(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        step_outcome: Any,
    ) -> FunctionCallingExecutionResult | None:
        if step_outcome.status == "completed":
            return self._build_completed_result(
                request=request,
                cursor=cursor,
                content=step_outcome.content,
                iteration=step_outcome.iteration,
            )
        if step_outcome.status == "cancelled":
            return self._build_cancelled_result(
                request=request,
                cursor=cursor,
                iteration=step_outcome.iteration,
                include_payload=False,
            )
        return None

    def _build_completed_result(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        content: str,
        iteration: int,
    ) -> FunctionCallingExecutionResult:
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=content,
            attachments=list(getattr(cursor.step_state, "chat_attachments", []) or []),
            message_payload=dict(getattr(cursor.step_state, "message_payload", {}) or {}),
            root_user_message=cursor.user_message,
            execution_outcome={
                "status": "completed",
                "content": content,
                "failure_reason": None,
                "tool_failures": list(getattr(cursor.step_state, "tool_failures", [])),
                "iterations": iteration,
            },
            turn_id=cursor.turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )

    def _build_cancelled_result(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        include_payload: bool,
        iteration: int | None = None,
    ) -> FunctionCallingExecutionResult:
        attachments = list(getattr(cursor.step_state, "chat_attachments", []) or [])
        message_payload = dict(getattr(cursor.step_state, "message_payload", {}) or {})
        execution_outcome: dict[str, Any] = {
            "status": "cancelled",
            "content": "",
            "failure_reason": None,
            "tool_failures": list(getattr(cursor.step_state, "tool_failures", [])),
            "iterations": cursor.step_state.iteration if iteration is None else iteration,
        }
        if include_payload:
            execution_outcome["attachments"] = attachments
            execution_outcome["message_payload"] = message_payload
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text="",
            attachments=attachments,
            message_payload=message_payload,
            root_user_message=cursor.user_message,
            execution_outcome=execution_outcome,
            turn_id=cursor.turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )

    def _build_detached_result_if_requested(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        detach_signal: DetachSignal | None,
    ) -> FunctionCallingExecutionResult | None:
        if detach_signal is None or not detach_signal.is_requested():
            return None
        return self._detached_result_builder(
            request=request,
            step_state=cursor.step_state,
            detach_signal=detach_signal,
            current_user_message=cursor.user_message,
            current_turn_id=cursor.turn_id,
        )

    async def _rebuild_from_active_run_if_needed(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        steer_inbox: SteerInbox | None,
    ) -> bool:
        active_run = self._deps.session_run_coordinator.get_active_run(
            request.context.session_id
        )
        if active_run is None or active_run.revision == cursor.revision:
            return False
        cursor.revision = active_run.revision
        cursor.user_message = str(active_run.root_user_message or cursor.user_message)
        cursor.turn_id = active_run.root_turn_id or cursor.turn_id
        cursor.step_state = self._build_step_state(request, cursor.user_message)
        if steer_inbox is not None:
            await steer_inbox.drain()
        return True

    def _rebuild_from_checkpoint_if_needed(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
    ) -> bool:
        checkpoint = self._deps.session_run_coordinator.consume_checkpoint(
            request.context.session_id
        )
        if not checkpoint.pending_turns:
            return False
        cursor.user_message = str(checkpoint.visible_user_message or cursor.user_message)
        cursor.turn_id = checkpoint.pending_turns[-1].turn_id or cursor.turn_id
        cursor.step_state = self._build_step_state(request, cursor.user_message)
        return True

    async def _run_fallback(
        self,
        *,
        request: FunctionCallingRequest,
        cursor: _LoopCursor,
        execution_workspace: str | None,
        cancel_token: CancelToken,
    ) -> FunctionCallingExecutionResult:
        fallback_control = (
            request.context.control
            if hasattr(request.context, "control") and request.context.control is not None
            else null_run_control()
        )
        fallback_control.cancel_token = cancel_token
        execution_outcome = (
            await self._deps.function_calling_orchestrator._execute_fallback_final_response(
                state=cursor.step_state,
                thinking_depth=request.thinking_depth,
                user_id=request.context.user_id,
                session_id=request.context.session_id,
                session_run_id=request.context.session_run_id,
                session_run_revision=cursor.revision,
                turn_id=cursor.turn_id,
                intent=request.intent.intent,
                execution_agent_id=request.context.runtime_key,
                execution_workspace=execution_workspace,
                llm_timeout_seconds=None,
                final_response_json_mode=False,
                cancel_token=cancel_token,
                control=fallback_control,
                route_decision=request.intent.route_decision,
            )
        )
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            attachments=list(getattr(execution_outcome, "attachments", []) or []),
            message_payload=dict(
                getattr(execution_outcome, "message_payload", {}) or {}
            ),
            root_user_message=cursor.user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=cursor.turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )


__all__ = ["FunctionCallingCheckpointLoop"]
