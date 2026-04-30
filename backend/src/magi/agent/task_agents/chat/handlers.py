"""Execution handlers for chat task-agent modes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ....core.logger import get_logger
from ....agent.background.dispatcher import (
    BackgroundDispatcher,
)
from ....agent.background.launch import BackgroundLaunchService
from ....agent.run_control import (
    DetachSignal,
    SteerInbox,
    bind_detach_signal,
)
from ....context.service import ContextAssemblyService
from ....context.scenarios import Scenario
from ..common import (
    BaseExecutionHandler,
    CommonHandlerDependencies,
    ExecutionHandlerRegistry,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    FactOnlyHandler,
    FunctionCallingExecutionResult,
    FunctionCallingRequest,
    OrchestrationLaunchHandler,
    OrchestrationUpdateHandler,
)
from .history_service import ChatHistoryService
from .planning_service import ChatPlanningService
from .prompt_service import ChatPromptService
from .direct_handler import DirectLLMHandler
from .explore_render import ExploreRenderHandler, start_explore_task_agent
from .runtime_control import FunctionCallingRuntimeControlMixin
from .handler_helpers import (
    build_attachment_preparation_guidance_block as _build_attachment_preparation_guidance_block,
    build_memory_query_guidance_block as _build_memory_query_guidance_block,
    build_scope_guidance_block as _build_scope_guidance_block,
    resolve_execution_workspace as _resolve_execution_workspace,
    resolve_turn_workspace_path as _resolve_turn_workspace_path,
    serialize_ux_plan as _serialize_ux_plan,
)
from ...task_orchestrator import TaskOrchestrator

logger = get_logger(__name__)


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


class FunctionCallingHandler(FunctionCallingRuntimeControlMixin, BaseExecutionHandler):
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
        attachment_guidance_block = _build_attachment_preparation_guidance_block(selected_tools)
        if attachment_guidance_block:
            system_prompt = f"{system_prompt}\n\n{attachment_guidance_block}"
        return FunctionCallingRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=self._deps.prompt_service.augment_system_prompt_with_reply_context(
                system_prompt=system_prompt,
                reply_context=getattr(request.context, "reply_context", None),
                recent_tool_state=getattr(request.context, "recent_tool_state", None),
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
                attachments=list(getattr(execution_outcome, "attachments", []) or []),
                message_payload=dict(getattr(execution_outcome, "message_payload", {}) or {}),
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
            allow_attachment_grounding=(
                bool(getattr(request.context, "allow_media_grounding_for_conversation", False))
                and bool(getattr(request.context, "core_model_supports_vision", False))
            ),
        )
        max_iterations = int(getattr(orchestrator, "MAX_ITERATIONS", 10) or 10)

        with bind_detach_signal(detach_signal):
            while step_state.iteration < max_iterations:
                if await cancel_token.is_cancelled():
                    return FunctionCallingExecutionResult(
                        mode=request.mode,
                        response_text="",
                        attachments=list(getattr(step_state, "chat_attachments", []) or []),
                        message_payload=dict(getattr(step_state, "message_payload", {}) or {}),
                        root_user_message=current_user_message,
                        execution_outcome={
                            "status": "cancelled",
                            "content": "",
                            "failure_reason": None,
                            "attachments": list(getattr(step_state, "chat_attachments", []) or []),
                            "message_payload": dict(getattr(step_state, "message_payload", {}) or {}),
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
                        attachments=list(getattr(step_state, "chat_attachments", []) or []),
                        message_payload=dict(getattr(step_state, "message_payload", {}) or {}),
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
                        allow_attachment_grounding=(
                            bool(getattr(request.context, "allow_media_grounding_for_conversation", False))
                            and bool(getattr(request.context, "core_model_supports_vision", False))
                        ),
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
                        allow_attachment_grounding=(
                            bool(getattr(request.context, "allow_media_grounding_for_conversation", False))
                            and bool(getattr(request.context, "core_model_supports_vision", False))
                        ),
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
            attachments=list(getattr(execution_outcome, "attachments", []) or []),
            message_payload=dict(getattr(execution_outcome, "message_payload", {}) or {}),
            root_user_message=current_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=current_turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )

async def _start_explore_task_agent(
    deps: ChatHandlerDependencies,
    request: ExecutionRequest,
) -> Optional[ExecutionResult]:
    return await start_explore_task_agent(deps, request)
