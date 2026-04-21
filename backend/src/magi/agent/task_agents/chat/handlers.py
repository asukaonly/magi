"""Execution handlers for chat task-agent modes."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ....config.models import ThinkingDepth
from ....core.logger import get_logger
from ....agent.message_utils import append_latest_user_message
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


StreamChunkCallback = Callable[[str, str, str | None, str, bool, bool], Awaitable[None]]


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
    stream_chunk_callback: StreamChunkCallback | None = None


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
        stream_callback = self._deps.stream_chunk_callback

        async def _capture_llm_trace(payload: dict[str, object]) -> None:
            llm_trace.update(payload)

        turn_id = getattr(request.context.latest_payload, "turn_id", None)

        if streaming_enabled and stream_callback is not None:
            chunks: list[str] = []
            async for chunk in self._deps.prompt_service.call_llm_stream(
                system_prompt=request.system_prompt,
                messages=request.messages,
                thinking_depth=request.thinking_depth,
            ):
                chunks.append(chunk)
                await stream_callback(
                    request.context.user_id,
                    request.context.session_id,
                    turn_id,
                    chunk,
                    False,
                    False,
                )
            response_text = "".join(chunks)
            await stream_callback(
                request.context.user_id,
                request.context.session_id,
                turn_id,
                "",
                True,
                False,
            )
            return ExecutionResult(
                mode=request.mode,
                response_text=response_text,
                root_user_message=request.context.latest_user_message,
                turn_id=turn_id,
                llm_trace=dict(llm_trace),
                ux_plan=_serialize_ux_plan(request.intent),
                streamed=True,
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
        if request.intent.memory_route == "explicit_query" and "memory_query" in selected_tools:
            selected_tools = ["memory_query"] + [tool for tool in selected_tools if tool != "memory_query"]
            memory_guidance_block = _build_memory_query_guidance_block(request.intent.routing_memory_hint)
            if memory_guidance_block:
                prompt_package.system_prompt = f"{prompt_package.system_prompt}\n\n{memory_guidance_block}"
        return FunctionCallingRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=self._deps.prompt_service.augment_system_prompt_with_reply_context(
                system_prompt=prompt_package.system_prompt,
                reply_context=getattr(request.context, "reply_context", None),
            ),
            selected_tools=selected_tools,
            thinking_depth=request.intent.thinking_depth,
        )

    async def execute(self, request: FunctionCallingRequest) -> ExecutionResult:
        execution_workspace = _resolve_execution_workspace(request)
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)
        stream_callback = self._deps.stream_chunk_callback
        turn_id = getattr(request.context.latest_payload, "turn_id", None)

        fc_stream_callback = None
        stream_state = {"chunks_emitted": 0, "retracted": False, "any_streamed": False}
        if streaming_enabled and stream_callback is not None:
            async def _fc_chunk_callback(text: str, is_step_final: bool = False) -> None:
                if is_step_final:
                    # Flush accumulated intermediate chunks so channels
                    # can deliver partial responses before tool execution.
                    if stream_state["chunks_emitted"] > 0:
                        await stream_callback(
                            request.context.user_id,
                            request.context.session_id,
                            turn_id,
                            "",
                            True,
                            False,
                        )
                        stream_state["chunks_emitted"] = 0
                    return
                stream_state["chunks_emitted"] += 1
                stream_state["any_streamed"] = True
                await stream_callback(
                    request.context.user_id,
                    request.context.session_id,
                    turn_id,
                    text,
                    False,
                    False,
                )

            fc_stream_callback = _fc_chunk_callback

        if (
            self._deps.session_run_coordinator is not None
            and request.context.session_run_id
            and hasattr(self._deps.function_calling_orchestrator, "step_executor")
            and hasattr(self._deps.function_calling_orchestrator, "build_step_state")
        ):
            result = await self._execute_with_session_checkpoints(
                request,
                execution_workspace=execution_workspace,
                stream_chunk_callback=fc_stream_callback,
            )
            result.streamed = stream_state.get("any_streamed", False)
            return result

        cancel_checker = self._build_cancel_checker(request)
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
            stream_chunk_callback=fc_stream_callback,
            cancel_checker=cancel_checker,
        )

        streamed = stream_state["chunks_emitted"] > 0 and execution_outcome.status == "completed"
        if streamed and stream_callback is not None:
            await stream_callback(
                request.context.user_id,
                request.context.session_id,
                turn_id,
                "",
                True,
                False,
            )

        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            root_user_message=request.context.latest_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
            streamed=streamed,
        )

    async def _execute_with_session_checkpoints(
        self,
        request: FunctionCallingRequest,
        *,
        execution_workspace: str | None,
        stream_chunk_callback: Any | None = None,
    ) -> ExecutionResult:
        orchestrator = self._deps.function_calling_orchestrator
        session_run_coordinator = self._deps.session_run_coordinator
        current_user_message = request.context.latest_user_message
        current_revision = int(getattr(request.context, "session_run_revision", 0) or 0)
        current_turn_id = getattr(request.context.latest_payload, "turn_id", None)
        cancel_checker = self._build_cancel_checker(request)
        step_state = orchestrator.build_step_state(
            user_message=current_user_message,
            system_prompt=request.system_prompt,
            selected_tools=request.selected_tools,
            conversation_history=request.context.history,
        )
        max_iterations = int(getattr(orchestrator, "MAX_ITERATIONS", 10) or 10)

        while step_state.iteration < max_iterations:
            if cancel_checker is not None and cancel_checker():
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
                stream_chunk_callback=stream_chunk_callback,
            )
            if step_outcome.status == "completed":
                # Flush any remaining intermediate streamed chunks.
                if stream_chunk_callback is not None:
                    await stream_chunk_callback("", True)
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

            # Flush intermediate streamed text before continuing.
            if stream_chunk_callback is not None:
                await stream_chunk_callback("", True)

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
            stream_chunk_callback=stream_chunk_callback,
            cancel_checker=cancel_checker,
        )
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            root_user_message=current_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=current_turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )

    def _build_cancel_checker(
        self, request: FunctionCallingRequest
    ) -> Callable[[], bool] | None:
        """Build a cancel-polling callable tied to the current session run.

        Returns ``None`` when no coordinator is available or the request is
        not bound to a session run (no cancellation is possible). The
        callable returns ``True`` once the coordinator has recorded a
        ``cancelling`` or ``cancelled`` status for the matching (session,
        run, revision) tuple.
        """
        coordinator = self._deps.session_run_coordinator
        session_id = str(request.context.session_id or "").strip()
        run_id = str(request.context.session_run_id or "").strip()
        if coordinator is None or not session_id or not run_id:
            return None
        revision = int(getattr(request.context, "session_run_revision", 0) or 0)

        def _check() -> bool:
            status = coordinator.get_run_status(
                session_id=session_id,
                run_id=run_id,
                revision=revision,
            )
            return status in ("cancelling", "cancelled")

        return _check


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
