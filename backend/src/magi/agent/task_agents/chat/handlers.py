"""Execution handlers for chat task-agent modes."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

from ....core.logger import get_logger
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


def _build_memory_query_guidance_block(memory_query_hint: dict | None) -> str:
    if not isinstance(memory_query_hint, dict) or not memory_query_hint:
        return ""
    hint_json = json.dumps(memory_query_hint, ensure_ascii=False)
    return "\n".join(
        [
            "# Memory Query Guidance",
            "Use `memory_query` before answering. Prefer these parameters for the first recall attempt:",
            hint_json,
        ]
    )


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
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
        )
        return DirectLLMRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=prompt_package.system_prompt,
            messages=request.context.history[-10:] + [
                {"role": "user", "content": request.context.latest_user_message}
            ],
            disable_thinking=not request.intent.deep_thinking,
        )

    async def execute(self, request: DirectLLMRequest) -> ExecutionResult:
        llm_trace: dict[str, object] = {}

        async def _capture_llm_trace(payload: dict[str, object]) -> None:
            llm_trace.update(payload)

        response_text = await self._deps.prompt_service.call_llm(
            system_prompt=request.system_prompt,
            messages=request.messages,
            disable_thinking=request.disable_thinking,
            llm_trace_callback=_capture_llm_trace,
        )
        return ExecutionResult(
            mode=request.mode,
            response_text=response_text,
            root_user_message=request.context.latest_user_message,
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
            llm_trace=dict(llm_trace),
        )


class FunctionCallingHandler(BaseExecutionHandler):
    mode = ExecutionMode.FUNCTION_CALLING

    async def build_request(self, request: ExecutionRequest) -> FunctionCallingRequest:
        prompt_package = await self._deps.context_service.build_prompt_package(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
        )
        selected_tools = list(request.tool_selection.tools)
        if request.intent.memory_route == "explicit_query" and "memory_query" in selected_tools:
            selected_tools = ["memory_query"] + [tool for tool in selected_tools if tool != "memory_query"]
            memory_guidance_block = _build_memory_query_guidance_block(request.intent.memory_query_hint)
            if memory_guidance_block:
                prompt_package.system_prompt = f"{prompt_package.system_prompt}\n\n{memory_guidance_block}"
        return FunctionCallingRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=prompt_package.system_prompt,
            selected_tools=selected_tools,
            disable_thinking=not request.intent.deep_thinking,
        )

    async def execute(self, request: FunctionCallingRequest) -> ExecutionResult:
        execution_outcome = await self._deps.function_calling_orchestrator.execute_with_tools(
            user_message=request.context.latest_user_message,
            system_prompt=request.system_prompt,
            selected_tools=request.selected_tools,
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
            conversation_history=request.context.history,
            disable_thinking=request.disable_thinking,
            intent=request.intent.intent,
            execution_agent_id=request.context.runtime_key,
            orchestration_strategy=(
                request.intent.orchestration_plan.to_strategy_dict()
                if request.intent.orchestration_plan is not None
                else None
            ),
        )
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            root_user_message=request.context.latest_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
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
        history_snapshot=history,
        upstream_task_agent_type=TaskAgentType.CHAT.value,
        upstream_task_agent_id=request.context.user_id,
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
        )
    deps.history_service.append_user_message(
        request.context.history_key,
        request.context.latest_user_message,
    )
    return ExecutionResult(
        mode=request.mode,
        skip_emit=True,
        turn_id=payload.turn_id,
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
                disable_thinking=True,
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
        )
