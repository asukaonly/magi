"""Execution handlers for chat task-agent modes."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from ....core.logger import get_logger
from ....core.runtime.contracts import FactRecord
from ....core.runtime.types import TaskAgentType
from ....memory.context_builder import Scenario
from ...task_orchestrator import TaskOrchestrator
from ..explore_task_agent import EXPLORE_TASK_REQUEST
from .contracts import ExecutionMode, ExecutionRequest, ExecutionResult
from .planning_service import ChatPlanningService
from .prompt_service import ChatPromptService
from .session_service import ChatSessionService

logger = get_logger(__name__)


class ExecutionHandler(Protocol):
    """Protocol for typed execution handlers."""

    mode: ExecutionMode

    def supports(self, mode: ExecutionMode) -> bool:
        """Return whether this handler supports the execution mode."""

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        """Prepare request payload for execution."""

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute a prepared request."""


class ExecutionHandlerRegistry:
    """Registry for execution handlers keyed by execution mode."""

    def __init__(self) -> None:
        self._handlers: dict[ExecutionMode, ExecutionHandler] = {}

    def register(self, handler: ExecutionHandler) -> None:
        self._handlers[handler.mode] = handler

    def get(self, mode: ExecutionMode) -> ExecutionHandler:
        handler = self._handlers.get(mode)
        if handler is None:
            raise KeyError(f"No execution handler registered for mode={mode}")
        return handler


@dataclass(slots=True)
class ChatHandlerDependencies:
    """Shared dependencies passed to chat execution handlers."""

    prompt_service: ChatPromptService
    planning_service: ChatPlanningService
    function_calling_executor: any
    task_orchestrator: TaskOrchestrator
    session_service: ChatSessionService
    agent_id: str


class BaseExecutionHandler:
    """Common execution-handler utilities."""

    mode: ExecutionMode

    def __init__(self, deps: ChatHandlerDependencies) -> None:
        self._deps = deps

    def supports(self, mode: ExecutionMode) -> bool:
        return mode == self.mode

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        return request


class FactOnlyHandler(BaseExecutionHandler):
    mode = ExecutionMode.FACT_ONLY

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(mode=request.mode, skip_emit=True)


class DirectLLMHandler(BaseExecutionHandler):
    mode = ExecutionMode.DIRECT_LLM

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        prompt_context = await self._deps.prompt_service.build_prompt_context(
            user_id=request.context.user_id,
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
        )
        request.prompt_payload = {
            "prompt_context": prompt_context,
            "system_prompt": self._deps.prompt_service.render_system_prompt(prompt_context),
            "messages": request.context.history[-10:] + [
                {"role": "user", "content": request.context.latest_user_message}
            ],
            "disable_thinking": not request.intent.deep_thinking,
        }
        return request

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        response_text = await self._deps.prompt_service.call_llm(
            system_prompt=request.prompt_payload["system_prompt"],
            messages=request.prompt_payload["messages"],
            disable_thinking=bool(request.prompt_payload["disable_thinking"]),
        )
        return ExecutionResult(
            mode=request.mode,
            response_text=response_text,
            root_user_message=request.context.latest_user_message,
        )


class FunctionCallingHandler(BaseExecutionHandler):
    mode = ExecutionMode.FUNCTION_CALLING

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        prompt_context = await self._deps.prompt_service.build_prompt_context(
            user_id=request.context.user_id,
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
        )
        request.prompt_payload = {
            "prompt_context": prompt_context,
            "system_prompt": self._deps.prompt_service.render_system_prompt(prompt_context),
        }
        request.tool_payload = {
            "selected_tools": request.tool_selection.tools,
            "disable_thinking": not request.intent.deep_thinking,
        }
        return request

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        execution_outcome = await self._deps.function_calling_executor.execute_with_tools(
            user_message=request.context.latest_user_message,
            system_prompt=request.prompt_payload["system_prompt"],
            selected_tools=request.tool_payload["selected_tools"],
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            conversation_history=request.context.history,
            disable_thinking=bool(request.tool_payload["disable_thinking"]),
            intent=request.intent.intent,
            execution_agent_id=request.context.runtime_key,
            orchestration_strategy=(
                request.intent.orchestration_plan.to_strategy_dict()
                if request.intent.orchestration_plan is not None
                else None
            ),
        )
        return ExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            root_user_message=request.context.latest_user_message,
            metadata={"execution_outcome": execution_outcome.to_dict()},
        )


class OrchestrationLaunchHandler(BaseExecutionHandler):
    mode = ExecutionMode.ORCHESTRATION_LAUNCH

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        request.metadata = {
            "correlation_id": request.context.latest_fact.correlation_id
            if isinstance(request.context.latest_fact, FactRecord)
            else None,
        }
        return request

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        orchestration_plan = request.intent.orchestration_plan
        if orchestration_plan is None:
            return ExecutionResult(
                mode=request.mode,
                response_text="Failed to generate orchestration strategy for this request.",
            )
        if orchestration_plan.route_to_explore_task_agent:
            return await self._start_explore_task_agent(request)
        raw_result = await self._deps.task_orchestrator.start_orchestration(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            history=request.context.history,
            history_key=request.context.history_key,
            correlation_id=request.metadata.get("correlation_id"),
            orchestration_strategy=orchestration_plan.to_strategy_dict(),
        )
        return ExecutionResult(
            mode=request.mode,
            response_text=str(raw_result.get("response", "")),
            skip_emit=bool(raw_result.get("skip_emit", False)),
            root_user_message=str(raw_result.get("root_user_message") or request.context.latest_user_message),
            correlation_id=raw_result.get("correlation_id"),
            orchestration_id=raw_result.get("orchestration_id"),
            message_started_at=raw_result.get("message_started_at"),
        )

    async def _start_explore_task_agent(self, request: ExecutionRequest) -> ExecutionResult:
        latest_fact = request.context.latest_fact
        history = self._deps.prompt_service.filter_history_for_aggregation(request.context.history)
        fact = FactRecord(
            agent_id=f"{TaskAgentType.EXPLORE.value}:{request.context.user_id}",
            event_type=EXPLORE_TASK_REQUEST,
            payload={
                "message": request.context.latest_user_message,
                "user_id": request.context.user_id,
                "session_id": request.context.session_id,
                "history_snapshot": history,
                "upstream_task_agent_type": TaskAgentType.CHAT.value,
                "upstream_task_agent_id": request.context.user_id,
            },
            agent_type=TaskAgentType.EXPLORE.value,
            agent_instance_id=request.context.user_id,
            timestamp=time.time(),
            correlation_id=latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
        )
        try:
            from ....runtime import get_agent_runtime

            runtime = get_agent_runtime()
            manager = runtime.get_task_agent_manager()
            enqueued = await manager.add_fact_to_agent(TaskAgentType.EXPLORE, request.context.user_id, fact)
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
            )
        self._deps.session_service.append_user_message(
            request.context.history_key,
            request.context.latest_user_message,
        )
        return ExecutionResult(mode=request.mode, skip_emit=True)


class OrchestrationUpdateHandler(BaseExecutionHandler):
    mode = ExecutionMode.ORCHESTRATION_UPDATE

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raw_result = await self._deps.task_orchestrator.process_worker_updates(request.context.batch_facts)
        return ExecutionResult(
            mode=request.mode,
            response_text=str(raw_result.get("response", "")),
            skip_emit=bool(raw_result.get("skip_emit", False)),
            root_user_message=str(raw_result.get("root_user_message") or request.context.latest_user_message),
            correlation_id=raw_result.get("correlation_id"),
            orchestration_id=raw_result.get("orchestration_id"),
            message_started_at=raw_result.get("message_started_at"),
        )


class ExploreRenderHandler(BaseExecutionHandler):
    mode = ExecutionMode.EXPLORE_TASK_RENDER

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        request.prompt_payload = {
            "markdown_dossier": str(request.context.latest_payload.get("markdown_dossier") or "").strip(),
            "root_user_message": str(
                request.context.latest_payload.get("root_user_message") or request.context.latest_user_message
            ).strip(),
            "message_started_at": request.context.latest_payload.get("message_started_at"),
            "orchestration_id": request.context.latest_payload.get("orchestration_id"),
        }
        return request

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        dossier = str(request.prompt_payload.get("markdown_dossier") or "").strip()
        root_user_message = str(request.prompt_payload.get("root_user_message") or request.context.latest_user_message).strip()
        orchestration_id = request.prompt_payload.get("orchestration_id")
        if not dossier:
            return ExecutionResult(
                mode=request.mode,
                response_text=self._deps.prompt_service.build_explore_render_fallback(root_user_message),
                root_user_message=root_user_message,
                correlation_id=request.context.latest_fact.correlation_id if isinstance(request.context.latest_fact, FactRecord) else None,
                orchestration_id=orchestration_id,
                message_started_at=request.prompt_payload.get("message_started_at"),
            )

        filtered_history = self._deps.prompt_service.filter_history_for_aggregation(request.context.history)
        system_prompt = await self._deps.prompt_service.build_system_prompt(
            user_id=request.context.user_id,
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
        return ExecutionResult(
            mode=request.mode,
            response_text=response.strip(),
            root_user_message=root_user_message,
            correlation_id=request.context.latest_fact.correlation_id if isinstance(request.context.latest_fact, FactRecord) else None,
            orchestration_id=orchestration_id,
            message_started_at=request.prompt_payload.get("message_started_at"),
        )
