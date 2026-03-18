"""Execution coordination for chat task agents."""
from __future__ import annotations

import platform
from datetime import datetime
from typing import Any

from ....core.logger import get_logger
from ....events.events import EventTypes
from ....tools.context_decider import ContextDecider
from ..common import (
    ExecutionMode,
    ExecutionRequest,
    OrchestrationPlan,
    ToolSelection,
)
from .contracts import ChatRuntimeContext, IntentDecision
from .fact_classifier import ChatFactClassifier
from .handlers import ExecutionHandlerRegistry

logger = get_logger(__name__)


class ChatExecutionCoordinator:
    """Coordinates intent routing, request building, and handler dispatch."""

    def __init__(
        self,
        *,
        context_decider: ContextDecider,
        fact_classifier: ChatFactClassifier,
        handler_registry: ExecutionHandlerRegistry,
    ) -> None:
        self._context_decider = context_decider
        self._fact_classifier = fact_classifier
        self._handler_registry = handler_registry

    async def match_intent(self, context: ChatRuntimeContext) -> IntentDecision:
        if context.incoming_fact_kind.value == "worker_update":
            return IntentDecision(
                intent="worker_orchestration_update",
                difficulty="normal",
                execution_mode=ExecutionMode.ORCHESTRATION_UPDATE,
                reasoning="Worker events must update orchestration state before any final response is emitted.",
            )
        if context.incoming_fact_kind.value == "explore_task_completed":
            return IntentDecision(
                intent="explore_task_completed",
                difficulty="normal",
                execution_mode=ExecutionMode.EXPLORE_TASK_RENDER,
                reasoning="ExploreTaskAgent produced a Markdown dossier that must be rendered back to the user.",
            )
        if isinstance(context.latest_fact, object) and getattr(context.latest_fact, "event_type", None) != EventTypes.USER_MESSAGE:
            return IntentDecision(
                intent="non_user_fact",
                difficulty="normal",
                execution_mode=ExecutionMode.FACT_ONLY,
                reasoning="Non-user fact does not require immediate LLM response.",
            )

        recent_messages: list[dict[str, str]] = []
        for msg in context.history[-6:]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "unknown"))
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            if len(content) > 120:
                content = content[:120] + "..."
            recent_messages.append({"role": role, "content": content})

        now = datetime.now()
        decision_context = {
            "os": platform.system(),
            "os_version": platform.release(),
            "current_datetime": now.isoformat(timespec="seconds"),
            "current_user": "unknown",
            "recent_messages": recent_messages,
            "recent_tool_errors": list(context.recent_tool_errors),
        }
        decision = await self._context_decider.decide(context.latest_user_message, decision_context)
        orchestration_plan = self._normalize_orchestration_plan(
            user_message=context.latest_user_message,
            strategy=decision.orchestration_strategy,
        )
        execution_mode = (
            ExecutionMode.ORCHESTRATION_LAUNCH
            if orchestration_plan.mode == "decompose"
            else ExecutionMode.FUNCTION_CALLING
            if decision.tools
            else ExecutionMode.DIRECT_LLM
        )
        return IntentDecision(
            intent=decision.intent,
            difficulty="hard" if decision.deep_thinking else "normal",
            execution_mode=execution_mode,
            tools=list(decision.tools),
            deep_thinking=bool(decision.deep_thinking),
            reasoning=str(decision.reasoning),
            orchestration_plan=orchestration_plan,
            memory_route=str(getattr(decision, "memory_route", "none") or "none"),
            memory_query_hint=getattr(decision, "memory_query_hint", None),
        )

    async def match_tools(self, context: ChatRuntimeContext, intent: IntentDecision) -> ToolSelection:
        _ = context
        if intent.execution_mode in {
            ExecutionMode.ORCHESTRATION_LAUNCH,
            ExecutionMode.ORCHESTRATION_UPDATE,
            ExecutionMode.FACT_ONLY,
            ExecutionMode.EXPLORE_TASK_RENDER,
        }:
            return ToolSelection(tools=[], reasoning=intent.reasoning)
        return ToolSelection(tools=list(intent.tools), reasoning=intent.reasoning)

    async def assemble_request(
        self,
        context: ChatRuntimeContext,
        intent: IntentDecision,
        tool_selection: ToolSelection,
    ) -> ExecutionRequest:
        request = ExecutionRequest(
            mode=intent.execution_mode,
            context=context,
            intent=intent,
            tool_selection=tool_selection,
        )
        handler = self._handler_registry.get(intent.execution_mode)
        return await handler.build_request(request)

    async def execute(self, request: ExecutionRequest):
        handler = self._handler_registry.get(request.mode)
        return await handler.execute(request)

    def _normalize_orchestration_plan(
        self,
        *,
        user_message: str,
        strategy: dict[str, Any],
    ) -> OrchestrationPlan:
        plan = OrchestrationPlan(
            mode=str(strategy.get("mode", "direct") or "direct"),
            planner=str(strategy.get("planner", "task_agent") or "task_agent"),
            default_leaf_type=str(strategy.get("default_leaf_type", "Explore") or "Explore"),
            allow_parallel=bool(strategy.get("allow_parallel", True)),
            route_to_explore_task_agent=False,
        )
        if plan.mode == "decompose" and plan.default_leaf_type == "Explore":
            lowered = user_message.lower()
            plan.route_to_explore_task_agent = any(
                keyword in lowered
                for keyword in [
                    "architecture",
                    "codebase",
                    "repo",
                    "跨模块",
                    "跨子系统",
                    "代码架构",
                    "项目架构",
                    "代码库",
                    "目录结构",
                ]
            )
        return plan
