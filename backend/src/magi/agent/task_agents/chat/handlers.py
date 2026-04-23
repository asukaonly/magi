"""Execution handlers for chat task-agent modes."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ....config.models import ThinkingDepth
from ....core.logger import get_logger
from ....agent.cancel import CancelToken, SessionRunCancelToken, null_cancel_token
from ....agent.background.contracts import BackgroundTaskTriggerSource
from ....agent.background.dispatcher import (
    BackgroundDecisionContext,
    BackgroundDecisionSource,
    BackgroundDispatcher,
)
from ....agent.background.launch import BackgroundLaunchService
from ....agent.message_utils import append_latest_user_message
from ....agent.run_control import (
    DetachSignal,
    OrchestratorSnapshot,
    SteerInbox,
    SteerMessage,
    bind_detach_signal,
)
from ....agent.runtime.contracts import FactRecord
from ....agent.runtime.types import TaskAgentType
from ....context.service import ContextAssemblyService
from ....context.scenarios import Scenario
from ..common import (
    BaseExecutionHandler,
    CommonHandlerDependencies,
    DirectLLMRequest,
    ExecutionHandlerRegistry,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExploreTaskCompletedPayload,
    ExploreTaskRequestPayload,
    ExploreRenderRequest,
    FactOnlyHandler,
    FunctionCallingExecutionResult,
    FunctionCallingRequest,
    OrchestrationLaunchHandler,
    OrchestrationUpdateHandler,
)
from ..explore.constants import EXPLORE_TASK_REQUEST
from .history_service import ChatHistoryService
from .planning_service import ChatPlanningService
from .prompt_service import ChatPromptService
from ...task_orchestrator import TaskOrchestrator

logger = get_logger(__name__)


# Translate a :class:`BackgroundDecisionSource` into the trigger source
# persisted with a :class:`BackgroundTaskSpec`. Kept at module scope so it
# does not rebuild on every dispatch.
_BACKGROUND_TRIGGER_SOURCE_BY_DECISION: dict[
    BackgroundDecisionSource, BackgroundTaskTriggerSource
] = {
    BackgroundDecisionSource.PLANNER: BackgroundTaskTriggerSource.PLANNER,
    BackgroundDecisionSource.RULE: BackgroundTaskTriggerSource.RULE,
    BackgroundDecisionSource.LLM: BackgroundTaskTriggerSource.CLASSIFIER,
    BackgroundDecisionSource.FALLBACK: BackgroundTaskTriggerSource.RULE,
}


def _build_memory_query_guidance_block(routing_memory_hint: dict | None) -> str:
    if not isinstance(routing_memory_hint, dict) or not routing_memory_hint:
        return ""
    hint_json = json.dumps(routing_memory_hint, ensure_ascii=False)
    return "\n".join(
        [
            "# Memory Query Guidance",
            "Use `memory_query` before answering. Prefer these parameters for the first recall attempt:",
            hint_json,
        ]
    )


def _build_scope_guidance_block(task_hint: dict | None) -> str:
    if not isinstance(task_hint, dict) or not task_hint:
        return ""

    target_locality = str(task_hint.get("target_locality") or "").strip()
    preferred_resolution_order = str(task_hint.get("preferred_resolution_order") or "").strip()
    requires_clarification = bool(task_hint.get("requires_clarification"))
    if not any([target_locality, preferred_resolution_order, requires_clarification]):
        return ""

    lines = [
        "# Scope Guidance",
        "Treat the current workspace as the default search boundary unless the user explicitly names another path.",
    ]
    if target_locality:
        lines.append(f"Target locality: {target_locality}")
    if preferred_resolution_order:
        lines.append(f"Preferred resolution order: {preferred_resolution_order}")
    if requires_clarification:
        lines.append(
            "If leaving the workspace would be required and the target location is still ambiguous, ask the user for a path or use web-search before any external local scan."
        )
    elif target_locality == "web":
        lines.append(
            "Prefer web-search or web-fetch over local repo discovery unless the user explicitly points to a local path."
        )
    return "\n".join(lines)


def _serialize_ux_plan(intent: object) -> dict | None:
    plan = getattr(intent, "ux_plan", None)
    if plan is None:
        return None
    to_dict = getattr(plan, "to_dict", None)
    return to_dict() if callable(to_dict) else plan


def _resolve_execution_workspace(request: FunctionCallingRequest) -> str | None:
    prompt_context = getattr(request, "prompt_context", None)
    runtime_system = getattr(prompt_context, "runtime_system", None)
    prompt_cwd = str(getattr(runtime_system, "cwd", "") or "").strip()
    if prompt_cwd:
        return prompt_cwd
    return _resolve_turn_workspace_path(request.context)


def _resolve_turn_workspace_path(context: object) -> str | None:
    latest_payload = getattr(context, "latest_payload", None)
    workspace_path = str(getattr(latest_payload, "workspace_path", "") or "").strip()
    return workspace_path or None


@dataclass(slots=True)
class ChatHandlerDependencies:
    """Shared dependencies passed to chat execution handlers."""

    context_service: ContextAssemblyService
    prompt_service: ChatPromptService
    planning_service: ChatPlanningService
    function_calling_orchestrator: any
    task_orchestrator: TaskOrchestrator
    history_service: ChatHistoryService
    agent_id: str
    get_task_agent_manager: callable
    session_run_coordinator: Any | None = None
    background_dispatcher: BackgroundDispatcher | None = None
    background_launch_service: BackgroundLaunchService | None = None
    persist_turn_supersessions: (
        Callable[[list[Any], int], Awaitable[None]] | None
    ) = None


def build_common_handler_dependencies(
    deps: ChatHandlerDependencies,
):
    return CommonHandlerDependencies(
        task_orchestrator=deps.task_orchestrator,
        start_specialized_orchestration=lambda request: _start_explore_task_agent(deps, request),
    )


class DirectLLMHandler(BaseExecutionHandler):
    mode = ExecutionMode.DIRECT_LLM

    async def build_request(self, request: ExecutionRequest) -> DirectLLMRequest:
        prompt_package = await self._deps.context_service.build_prompt_package(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            attachments=list(getattr(request.context.latest_payload, "attachments", []) or []),
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
            workspace_path=_resolve_turn_workspace_path(request.context),
        )
        return DirectLLMRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=self._deps.prompt_service.augment_system_prompt_with_reply_context(
                system_prompt=prompt_package.system_prompt,
                reply_context=getattr(request.context, "reply_context", None),
            ),
            messages=append_latest_user_message(
                request.context.history,
                request.context.latest_user_message,
                history_limit=10,
                attachments=list(getattr(request.context.latest_payload, "attachments", []) or []),
            ),
            thinking_depth=request.intent.thinking_depth,
        )

    async def execute(self, request: DirectLLMRequest) -> ExecutionResult:
        llm_trace: dict[str, object] = {}
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)

        async def _capture_llm_trace(payload: dict[str, object]) -> None:
            llm_trace.update(payload)

        turn_id = getattr(request.context.latest_payload, "turn_id", None)

        if streaming_enabled:
            chunks: list[str] = []
            async for event in self._deps.prompt_service.call_llm_stream(
                system_prompt=request.system_prompt,
                messages=request.messages,
                thinking_depth=request.thinking_depth,
            ):
                if event.kind == "text_delta" and event.text:
                    chunks.append(event.text)
            response_text = "".join(chunks)
            return ExecutionResult(
                mode=request.mode,
                response_text=response_text,
                root_user_message=request.context.latest_user_message,
                turn_id=turn_id,
                llm_trace=dict(llm_trace),
                ux_plan=_serialize_ux_plan(request.intent),
                streamed=bool(response_text),
            )

        response_text = await self._deps.prompt_service.call_llm(
            system_prompt=request.system_prompt,
            messages=request.messages,
            thinking_depth=request.thinking_depth,
            llm_trace_callback=_capture_llm_trace,
        )
        return ExecutionResult(
            mode=request.mode,
            response_text=response_text,
            root_user_message=request.context.latest_user_message,
            turn_id=turn_id,
            llm_trace=dict(llm_trace),
            ux_plan=_serialize_ux_plan(request.intent),
        )


class FunctionCallingHandler(BaseExecutionHandler):
    mode = ExecutionMode.FUNCTION_CALLING

    async def build_request(self, request: ExecutionRequest) -> FunctionCallingRequest:
        prompt_package = await self._deps.context_service.build_prompt_package(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            attachments=list(getattr(request.context.latest_payload, "attachments", []) or []),
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
            workspace_path=_resolve_turn_workspace_path(request.context),
        )
        selected_tools = list(request.tool_selection.tools)
        system_prompt = prompt_package.system_prompt
        if request.intent.memory_route == "explicit_query" and "memory_query" in selected_tools:
            selected_tools = ["memory_query"] + [tool for tool in selected_tools if tool != "memory_query"]
            memory_guidance_block = _build_memory_query_guidance_block(request.intent.routing_memory_hint)
            if memory_guidance_block:
                system_prompt = f"{system_prompt}\n\n{memory_guidance_block}"
        scope_guidance_block = _build_scope_guidance_block(
            getattr(request.tool_selection, "task_hint", None) or getattr(request.intent, "task_hint", None)
        )
        if scope_guidance_block:
            system_prompt = f"{system_prompt}\n\n{scope_guidance_block}"
        return FunctionCallingRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=self._deps.prompt_service.augment_system_prompt_with_reply_context(
                system_prompt=system_prompt,
                reply_context=getattr(request.context, "reply_context", None),
            ),
            selected_tools=selected_tools,
            thinking_depth=request.intent.thinking_depth,
        )

    async def execute(self, request: FunctionCallingRequest) -> ExecutionResult:
        background_result = await self._maybe_dispatch_to_background(request)
        if background_result is not None:
            return background_result
        execution_workspace = _resolve_execution_workspace(request)
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)
        turn_id = getattr(request.context.latest_payload, "turn_id", None)
        session_id = str(getattr(request.context, "session_id", "") or "").strip()
        detach_signal = self._build_detach_signal(session_id=session_id)
        steer_inbox = await self._build_steer_inbox(request)
        try:
            if (
                self._deps.session_run_coordinator is not None
                and request.context.session_run_id
                and hasattr(self._deps.function_calling_orchestrator, "step_executor")
                and hasattr(self._deps.function_calling_orchestrator, "build_step_state")
            ):
                result = await self._execute_with_session_checkpoints(
                    request,
                    execution_workspace=execution_workspace,
                    detach_signal=detach_signal,
                    steer_inbox=steer_inbox,
                )
                result.streamed = streaming_enabled
                handoff = await self._maybe_handoff_detached_outcome(request, result)
                if handoff is not None:
                    return handoff
                return result

            cancel_token = self._build_cancel_token(request)
            execution_outcome = await self._deps.function_calling_orchestrator.execute_with_tools(
                user_message=request.context.latest_user_message,
                system_prompt=request.system_prompt,
                selected_tools=request.selected_tools,
                user_id=request.context.user_id,
                session_id=request.context.session_id,
                session_run_id=request.context.session_run_id,
                session_run_revision=request.context.session_run_revision,
                turn_id=turn_id,
                conversation_history=request.context.history,
                thinking_depth=request.thinking_depth,
                intent=request.intent.intent,
                execution_agent_id=request.context.runtime_key,
                execution_workspace=execution_workspace,
                orchestration_strategy=(
                    request.intent.orchestration_plan.to_strategy_dict()
                    if request.intent.orchestration_plan is not None
                    else None
                ),
                cancel_token=cancel_token,
                detach_signal=detach_signal,
                steer_inbox=steer_inbox,
            )

            streamed = streaming_enabled and execution_outcome.status == "completed"

            fc_result = FunctionCallingExecutionResult(
                mode=request.mode,
                response_text=execution_outcome.content,
                root_user_message=request.context.latest_user_message,
                execution_outcome=execution_outcome.to_dict(),
                turn_id=turn_id,
                ux_plan=_serialize_ux_plan(request.intent),
                streamed=streamed,
            )
            handoff = await self._maybe_handoff_detached_outcome(request, fc_result)
            if handoff is not None:
                return handoff
            return fc_result
        finally:
            self._release_detach_signal(session_id=session_id, detach_signal=detach_signal)

    async def _execute_with_session_checkpoints(
        self,
        request: FunctionCallingRequest,
        *,
        execution_workspace: str | None,
        detach_signal: DetachSignal | None = None,
        steer_inbox: SteerInbox | None = None,
    ) -> ExecutionResult:
        orchestrator = self._deps.function_calling_orchestrator
        session_run_coordinator = self._deps.session_run_coordinator
        current_user_message = request.context.latest_user_message
        current_revision = int(getattr(request.context, "session_run_revision", 0) or 0)
        current_turn_id = getattr(request.context.latest_payload, "turn_id", None)
        cancel_token = self._build_cancel_token(request)
        step_state = orchestrator.build_step_state(
            user_message=current_user_message,
            system_prompt=request.system_prompt,
            selected_tools=request.selected_tools,
            conversation_history=request.context.history,
        )
        max_iterations = int(getattr(orchestrator, "MAX_ITERATIONS", 10) or 10)

        with bind_detach_signal(detach_signal):
            while step_state.iteration < max_iterations:
                if await cancel_token.is_cancelled():
                    return FunctionCallingExecutionResult(
                        mode=request.mode,
                        response_text="",
                        root_user_message=current_user_message,
                        execution_outcome={
                            "status": "cancelled",
                            "content": "",
                            "failure_reason": None,
                            "tool_failures": list(getattr(step_state, "tool_failures", [])),
                            "iterations": step_state.iteration,
                        },
                        turn_id=current_turn_id,
                        ux_plan=_serialize_ux_plan(request.intent),
                    )
                if detach_signal is not None and detach_signal.is_requested():
                    return self._build_detached_chat_result(
                        request=request,
                        step_state=step_state,
                        detach_signal=detach_signal,
                        current_user_message=current_user_message,
                        current_turn_id=current_turn_id,
                    )
                await self._drain_pending_steer_turns(
                    session_id=request.context.session_id,
                    revision=current_revision,
                    steer_inbox=steer_inbox,
                    step_state=step_state,
                    latest_fact_timestamp=getattr(
                        request.context.latest_payload, "timestamp", None
                    ),
                )
                step_outcome = await orchestrator.step_executor.execute_step(
                    state=step_state,
                    user_message=current_user_message,
                    thinking_depth=request.thinking_depth,
                    user_id=request.context.user_id,
                    session_id=request.context.session_id,
                    session_run_id=request.context.session_run_id,
                    session_run_revision=current_revision,
                    turn_id=current_turn_id,
                    intent=request.intent.intent,
                    execution_agent_id=request.context.runtime_key,
                    execution_workspace=execution_workspace,
                    orchestration_strategy=(
                        request.intent.orchestration_plan.to_strategy_dict()
                        if request.intent.orchestration_plan is not None
                        else None
                    ),
                )
                if step_outcome.status == "completed":
                    execution_outcome = {
                        "status": "completed",
                        "content": step_outcome.content,
                        "failure_reason": None,
                        "tool_failures": list(getattr(step_state, "tool_failures", [])),
                        "iterations": step_outcome.iteration,
                    }
                    return FunctionCallingExecutionResult(
                        mode=request.mode,
                        response_text=step_outcome.content,
                        root_user_message=current_user_message,
                        execution_outcome=execution_outcome,
                        turn_id=current_turn_id,
                        ux_plan=_serialize_ux_plan(request.intent),
                    )
                if step_outcome.status == "failed":
                    # Instead of returning an empty response, let the LLM
                    # generate a final answer using the error context.
                    break

                # Re-check detach after the tool batch runs so a tool that
                # flipped the signal this iteration exits before the next
                # LLM call.
                if detach_signal is not None and detach_signal.is_requested():
                    return self._build_detached_chat_result(
                        request=request,
                        step_state=step_state,
                        detach_signal=detach_signal,
                        current_user_message=current_user_message,
                        current_turn_id=current_turn_id,
                    )

                active_run = session_run_coordinator.get_active_run(request.context.session_id)
                if active_run is not None and active_run.revision != current_revision:
                    current_revision = active_run.revision
                    current_user_message = str(active_run.root_user_message or current_user_message)
                    current_turn_id = active_run.root_turn_id or current_turn_id
                    step_state = orchestrator.build_step_state(
                        user_message=current_user_message,
                        system_prompt=request.system_prompt,
                        selected_tools=request.selected_tools,
                        conversation_history=request.context.history,
                    )
                    if steer_inbox is not None:
                        # Pending STEER turns from the prior revision are no
                        # longer relevant once the run is rebuilt from a new
                        # root, so drop anything still queued in-process.
                        await steer_inbox.drain()
                    continue

                checkpoint = session_run_coordinator.consume_checkpoint(request.context.session_id)
                if checkpoint.pending_turns:
                    current_user_message = str(checkpoint.visible_user_message or current_user_message)
                    current_turn_id = checkpoint.pending_turns[-1].turn_id or current_turn_id
                    step_state = orchestrator.build_step_state(
                        user_message=current_user_message,
                        system_prompt=request.system_prompt,
                        selected_tools=request.selected_tools,
                        conversation_history=request.context.history,
                    )
                    continue

            execution_outcome = await orchestrator._execute_fallback_final_response(
                state=step_state,
                thinking_depth=request.thinking_depth,
                user_id=request.context.user_id,
                session_id=request.context.session_id,
                session_run_id=request.context.session_run_id,
                session_run_revision=current_revision,
                turn_id=current_turn_id,
                intent=request.intent.intent,
                execution_agent_id=request.context.runtime_key,
                execution_workspace=execution_workspace,
                orchestration_strategy=(
                    request.intent.orchestration_plan.to_strategy_dict()
                    if request.intent.orchestration_plan is not None
                    else None
                ),
                llm_timeout_seconds=None,
                final_response_json_mode=False,
                cancel_token=cancel_token,
            )
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            root_user_message=current_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=current_turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )

    def _build_detached_chat_result(
        self,
        *,
        request: FunctionCallingRequest,
        step_state: Any,
        detach_signal: DetachSignal,
        current_user_message: str,
        current_turn_id: str | None,
    ) -> "FunctionCallingExecutionResult":
        """Wrap a detach-triggered exit as a ``FunctionCallingExecutionResult``.

        Produces the same ``execution_outcome`` shape that
        :meth:`ExecutionOutcome.to_dict` would emit from
        :meth:`FunctionCallingOrchestrator._build_detached_outcome`, so
        downstream handoff logic only needs one code path.
        """
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
            root_user_message=current_user_message,
            execution_outcome={
                "status": "detached",
                "content": "",
                "failure_reason": None,
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
        """Delegate to the background runtime when the dispatcher agrees.

        Returns a final :class:`ExecutionResult` carrying a short ack
        when the turn has been routed to the background task manager,
        or ``None`` when the foreground path should proceed as usual.
        Any dispatcher / launch failure degrades silently to foreground.
        """
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

    def _build_detach_signal(self, *, session_id: str) -> DetachSignal | None:
        """Return a fresh :class:`DetachSignal` for this turn, or ``None``.

        The signal is only useful when a :class:`BackgroundLaunchService`
        is wired — otherwise there is no place to hand the run off to and
        the ``detach_to_background`` tool should continue to surface as
        unsupported. Returning ``None`` in that case keeps
        :func:`bind_detach_signal` a no-op.
        """
        if self._deps.background_launch_service is None:
            return None
        signal = DetachSignal()
        coordinator = self._deps.session_run_coordinator
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
        """Return an empty :class:`SteerInbox` for this turn, or ``None``.

        Without a :class:`SessionRunCoordinator` there is no persistent
        queue to drain, so returning ``None`` keeps the orchestrator's
        steer path a no-op. When a coordinator is wired we return a
        fresh empty inbox — any persisted STEER pending turns (including
        ones that survived a backend restart) are drained into it at the
        top of the first checkpoint iteration by
        :meth:`_drain_pending_steer_turns`, which also emits supersession
        bookkeeping. Draining here would bypass that bookkeeping.
        """
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
        """Pull freshly persisted STEER turns into ``steer_inbox``.

        Called at the top of each checkpoint iteration so STEER turns
        that arrived while the previous tool batch was running get
        injected into ``state.messages`` before the next LLM call.
        Emits supersession bookkeeping (root + intermediate STEER
        pending turns → the newest drained turn) so downstream
        timeline/trace persistence mirrors the AUGMENT merge shape.
        """
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
            # The inbox may already carry messages from a previous
            # iteration (e.g. hydrated at turn start). Drain-and-apply
            # still needs to run so they land on ``state.messages``.
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

        # Bookkeeping: mark root + intermediate STEER pending turns as
        # superseded by the newest drained turn, same shape as AUGMENT.
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
        """If ``result`` carries a ``detached`` outcome, enqueue a background
        task seeded from its snapshot and return the ack result.

        Returns ``None`` when the result is not a detach (so callers fall
        through to their normal return path) or when no launch service is
        wired. Any launch failure degrades silently and the original
        detached result is returned so the chat surface shows an error
        rather than pretending the work continues.
        """
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
        try:
            return await launch_service.enqueue_from_request(
                request,
                trigger_source=BackgroundTaskTriggerSource.MANUAL,
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

    def _build_cancel_token(
        self, request: FunctionCallingRequest
    ) -> CancelToken:
        """Build a :class:`CancelToken` bound to one specific run revision.

        The returned token is pinned to the ``(session_id, run_id,
        revision)`` triple captured at build time. ``is_cancelled()``
        resolves to ``True`` **only** when
        :meth:`SessionRunCoordinator.get_run_status` reports the active
        run for that exact triple is ``cancelling`` or ``cancelled``. In
        every other case it resolves to ``False``:

        * No coordinator is wired, or the request is not bound to a session
          run → the noop token is returned and no polling occurs.
        * The active run has been completed / cleared (``get_run_status``
          returns ``None``) → ``False``.
        * A new ``run_id`` has replaced the one we were bound to →
          ``False``.
        * The ``revision`` has advanced (e.g. ``bump_revision`` after an
          INTERRUPT) without an explicit ``request_cancel`` → ``False``.
          The superseded tool-loop is expected to finish naturally; its
          result will be flagged ``stale`` by
          :meth:`SessionRunCoordinator.record_result`.
        * The active run is ``running`` → ``False``.

        This means the token is a **narrow, opt-in stop signal**: a tool
        loop will only abort when someone has *explicitly* requested
        cancellation on the exact run/revision it was launched for.
        Callers that want to react to supersession (revision bump) must
        wire a separate signal.
        """
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


async def _start_explore_task_agent(
    deps: ChatHandlerDependencies,
    request: ExecutionRequest,
) -> Optional[ExecutionResult]:
    orchestration_plan = request.intent.orchestration_plan
    if orchestration_plan is None or not orchestration_plan.route_to_explore_task_agent:
        return None
    latest_fact = request.context.latest_fact
    history = deps.prompt_service.filter_history_for_aggregation(request.context.history)
    payload = ExploreTaskRequestPayload(
        user_id=request.context.user_id,
        session_id=request.context.session_id,
        content=request.context.latest_user_message,
        run_id=request.context.session_run_id,
        run_revision=request.context.session_run_revision,
        history_snapshot=history,
        upstream_task_agent_type=TaskAgentType.CHAT.value,
        upstream_task_agent_id=request.context.session_id or request.context.user_id,
        turn_id=getattr(request.context.latest_payload, "turn_id", None),
    )
    fact = FactRecord(
        agent_id=f"{TaskAgentType.EXPLORE.value}:{request.context.user_id}",
        event_type=EXPLORE_TASK_REQUEST,
        payload=payload.to_dict(),
        agent_type=TaskAgentType.EXPLORE.value,
        agent_instance_id=request.context.user_id,
        timestamp=time.time(),
        correlation_id=latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
    )
    manager = deps.get_task_agent_manager()
    try:
        enqueued = False if manager is None else await manager.add_fact_to_agent(TaskAgentType.EXPLORE, request.context.user_id, fact)
    except Exception as exc:
        logger.warning(
            "Failed to route request to ExploreTaskAgent | user_id=%s error=%s",
            request.context.user_id,
            exc,
        )
        enqueued = False
    if not enqueued:
        return ExecutionResult(
            mode=request.mode,
            response_text="Failed to start Explore task decomposition for this request.",
            root_user_message=request.context.latest_user_message,
            correlation_id=fact.correlation_id,
            turn_id=payload.turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )
    deps.history_service.append_user_message(
        request.context.history_key,
        request.context.latest_user_message,
    )
    return ExecutionResult(
        mode=request.mode,
        skip_emit=True,
        turn_id=payload.turn_id,
        ux_plan=_serialize_ux_plan(request.intent),
    )


class ExploreRenderHandler(BaseExecutionHandler):
    mode = ExecutionMode.EXPLORE_TASK_RENDER

    async def build_request(self, request: ExecutionRequest) -> ExploreRenderRequest:
        latest_payload = request.context.latest_payload
        return ExploreRenderRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            markdown_dossier=(
                latest_payload.markdown_dossier
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else ""
            ),
            root_user_message=(
                latest_payload.root_user_message
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else request.context.latest_user_message
            ).strip(),
            message_started_at=(
                latest_payload.message_started_at
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else None
            ),
            orchestration_id=(
                latest_payload.orchestration_id
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else None
            ),
        )

    async def execute(self, request: ExploreRenderRequest) -> ExecutionResult:
        dossier = request.markdown_dossier
        root_user_message = str(request.root_user_message or request.context.latest_user_message).strip()
        orchestration_id = request.orchestration_id
        if not dossier:
            return ExecutionResult(
                mode=request.mode,
                response_text=self._deps.prompt_service.build_explore_render_fallback(root_user_message),
                root_user_message=root_user_message,
                correlation_id=request.context.latest_fact.correlation_id if isinstance(request.context.latest_fact, FactRecord) else None,
                orchestration_id=orchestration_id,
                message_started_at=request.message_started_at,
                turn_id=getattr(request.context.latest_payload, "turn_id", None),
                ux_plan=_serialize_ux_plan(request.intent),
            )

        filtered_history = self._deps.prompt_service.filter_history_for_aggregation(request.context.history)
        system_prompt = await self._deps.context_service.build_system_prompt(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=root_user_message,
            task_category="analysis",
            scenario=Scenario.ANALYSIS,
        )
        messages = filtered_history + [
            {
                "role": "user",
                "content": self._deps.prompt_service.build_explore_render_message(root_user_message, dossier),
            }
        ]
        try:
            response = await self._deps.prompt_service.call_llm(
                system_prompt=system_prompt,
                messages=messages,
                thinking_depth=ThinkingDepth.NONE,
            )
        except Exception as exc:
            logger.warning(
                "Explore dossier rendering failed | orchestration_id=%s error=%s",
                orchestration_id,
                exc,
            )
            response = ""
        if not response.strip():
            logger.warning(
                "Explore dossier rendering returned empty response | orchestration_id=%s dossier_preview=%s",
                orchestration_id,
                dossier[:300],
            )
            response = self._deps.prompt_service.build_explore_render_fallback(root_user_message, dossier)
        response = self._deps.prompt_service.format_explore_render_response(response)
        return ExecutionResult(
            mode=request.mode,
            response_text=response.strip(),
            root_user_message=root_user_message,
            correlation_id=request.context.latest_fact.correlation_id if isinstance(request.context.latest_fact, FactRecord) else None,
            orchestration_id=orchestration_id,
            message_started_at=request.message_started_at,
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
            ux_plan=_serialize_ux_plan(request.intent),
        )
