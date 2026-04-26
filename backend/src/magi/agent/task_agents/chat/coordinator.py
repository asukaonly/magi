"""Execution coordination for chat task agents."""
from __future__ import annotations

import inspect
import os
import platform
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List

from ....agent.message_utils import build_recent_messages
from ....core.logger import get_logger
from ....tools.context_decider import ContextDecider
from ....tools.context_decider_context import ContextDeciderContext
from ..common import (
    ExecutionMode,
    ExecutionRequest,
    IncomingFactKind,
    OrchestrationPlan,
    ToolSelection,
)
from .contracts import (
    AssistantSurfaceMode,
    ChatRuntimeContext,
    IntentDecision,
    ThinkingIndicatorMode,
    TraceDisplayMode,
    TurnUXPlan,
)
from .fact_classifier import ChatFactClassifier
from .handlers import ExecutionHandlerRegistry

logger = get_logger(__name__)

# Tools the execution LLM always has access to when tool-calling is active,
# regardless of what the Context Decider selected.  This avoids the routing
# LLM becoming a single point of failure for tool availability.
_FALLBACK_TOOLS = ["web-search"]

IntentTraceCallback = Callable[[ChatRuntimeContext, IntentDecision], Awaitable[None] | None]
ToolAdvisoryProvider = Callable[[str | None], Awaitable[List[Dict[str, Any]]]]


class ChatExecutionCoordinator:
    """Coordinates intent routing, request building, and handler dispatch."""

    _REACTION_ONLY_ACKS = {
        "嗯",
        "嗯嗯",
        "恩",
        "哦",
        "ok",
        "okay",
        "好的",
        "收到",
        "明白",
    }

    def __init__(
        self,
        *,
        context_decider: ContextDecider,
        fact_classifier: ChatFactClassifier,
        handler_registry: ExecutionHandlerRegistry,
        intent_trace_callback: IntentTraceCallback | None = None,
        tool_advisory_provider: ToolAdvisoryProvider | None = None,
    ) -> None:
        self._context_decider = context_decider
        self._fact_classifier = fact_classifier
        self._handler_registry = handler_registry
        self._intent_trace_callback = intent_trace_callback
        self._tool_advisory_provider = tool_advisory_provider

    async def match_intent(self, context: ChatRuntimeContext) -> IntentDecision:
        planner_fact_kind = (
            context.planner_fact_kind
            if context.planner_fact is not None or context.planner_fact_kind != IncomingFactKind.OTHER_FACT
            else context.incoming_fact_kind
        )
        if planner_fact_kind == IncomingFactKind.WORKER_UPDATE:
            return IntentDecision(
                intent="worker_orchestration_update",
                difficulty="normal",
                execution_mode=ExecutionMode.ORCHESTRATION_UPDATE,
                reasoning="Worker events must update orchestration state before any final response is emitted.",
                ux_plan=self._build_turn_ux_plan(
                    user_message=context.latest_user_message,
                    execution_mode=ExecutionMode.ORCHESTRATION_UPDATE,
                    tools=[],
                    orchestration_plan=None,
                ),
            )
        if planner_fact_kind == IncomingFactKind.EXPLORE_TASK_COMPLETED:
            return IntentDecision(
                intent="explore_task_completed",
                difficulty="normal",
                execution_mode=ExecutionMode.EXPLORE_TASK_RENDER,
                reasoning="ExploreTaskAgent produced a Markdown dossier that must be rendered back to the user.",
                ux_plan=self._build_turn_ux_plan(
                    user_message=context.latest_user_message,
                    execution_mode=ExecutionMode.EXPLORE_TASK_RENDER,
                    tools=[],
                    orchestration_plan=None,
                ),
            )
        if planner_fact_kind == IncomingFactKind.OTHER_FACT:
            return IntentDecision(
                intent="non_user_fact",
                difficulty="normal",
                execution_mode=ExecutionMode.FACT_ONLY,
                reasoning="Non-user fact does not require immediate LLM response.",
                ux_plan=self._build_turn_ux_plan(
                    user_message=context.latest_user_message,
                    execution_mode=ExecutionMode.FACT_ONLY,
                    tools=[],
                    orchestration_plan=None,
                ),
            )

        recent_messages = build_recent_messages(
            context.history,
            limit=6,
            content_limit=120,
            exclude_latest_user_message=context.latest_user_message,
        )

        now = datetime.now().astimezone()
        decision_context = ContextDeciderContext(
            os_name=platform.system(),
            os_version=platform.release(),
            current_datetime=now.isoformat(timespec="seconds"),
            timezone=str(now.tzinfo or "unknown"),
            workspace_path=str(getattr(context.latest_payload, "workspace_path", "") or ""),
            home_dir=os.path.expanduser("~"),
            current_user="unknown",
            recent_messages=recent_messages,
            recent_tool_errors=list(context.recent_tool_errors),
            recent_tool_state=list(context.recent_tool_state),
        )

        # Inject L4 procedural-memory advisory if provider is available.
        if self._tool_advisory_provider is not None:
            try:
                advisories = await self._tool_advisory_provider(context.latest_user_message)
                if advisories:
                    decision_context.tool_advisory = advisories
            except Exception as exc:
                logger.debug("Failed to fetch tool advisory: %s", exc)

        decision = await self._context_decider.decide(context.latest_user_message, decision_context)
        orchestration_plan = self._normalize_orchestration_plan(
            user_message=context.latest_user_message,
            strategy=decision.orchestration_strategy,
        )
        has_image_attachments = any(
            isinstance(item, dict) and str(item.get("kind") or "").strip() == "image"
            for item in list(getattr(context.latest_payload, "attachments", []) or [])
        )
        selected_tools = [] if has_image_attachments else list(decision.tools)
        # Ensure fallback tools are always available when tool-assisted execution
        # is active.  The execution LLM is smarter than the routing LLM and can
        # decide on its own whether web-search is useful for the current task.
        if selected_tools:
            registered = set(self._context_decider.tool_registry.list_tools())
            for ft in _FALLBACK_TOOLS:
                if ft not in selected_tools and ft in registered:
                    selected_tools.append(ft)
        execution_mode = (
            ExecutionMode.DIRECT_LLM
            if has_image_attachments
            else ExecutionMode.ORCHESTRATION_LAUNCH
            if orchestration_plan.mode == "decompose"
            else ExecutionMode.FUNCTION_CALLING
            if selected_tools
            else ExecutionMode.DIRECT_LLM
        )
        intent_decision = IntentDecision(
            intent=decision.intent,
            difficulty="hard" if decision.deep_thinking else "normal",
            execution_mode=execution_mode,
            ux_plan=self._build_turn_ux_plan(
                user_message=context.latest_user_message,
                execution_mode=execution_mode,
                tools=selected_tools,
                orchestration_plan=orchestration_plan,
            ),
            tools=selected_tools,
            llm_trace=dict(getattr(decision, "llm_trace", {}) or {}),
            thinking_depth=decision.thinking_depth,
            reasoning=str(decision.reasoning),
            orchestration_plan=orchestration_plan,
            memory_route=str(getattr(decision, "memory_route", "none") or "none"),
        )
        if self._intent_trace_callback is not None:
            callback_result = self._intent_trace_callback(context, intent_decision)
            if inspect.isawaitable(callback_result):
                await callback_result
        return intent_decision

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

    def _build_turn_ux_plan(
        self,
        *,
        user_message: str,
        execution_mode: ExecutionMode,
        tools: list[str],
        orchestration_plan: OrchestrationPlan | None,
    ) -> TurnUXPlan:
        normalized_message = str(user_message or "").strip().lower()
        if execution_mode == ExecutionMode.FACT_ONLY:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.NONE,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.NONE,
            )
        if execution_mode == ExecutionMode.DIRECT_LLM:
            if normalized_message in self._REACTION_ONLY_ACKS:
                return TurnUXPlan(
                    assistant_surface_mode=AssistantSurfaceMode.REACTION_ONLY,
                    thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                    trace_display_mode=TraceDisplayMode.NONE,
                    reaction_style="acknowledge",
                )
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.NONE,
            )
        if execution_mode == ExecutionMode.FUNCTION_CALLING:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.COLLAPSIBLE,
                allow_trace_collapse=bool(tools),
            )
        if execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH:
            interim_text = "Let me think this through and check for you."
            if orchestration_plan is not None and orchestration_plan.route_to_explore_task_agent:
                interim_text = "Let me inspect this in detail and I will come back with the result."
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.INTERIM_THEN_FINAL,
                thinking_indicator=ThinkingIndicatorMode.SUBTLE,
                trace_display_mode=TraceDisplayMode.COLLAPSIBLE,
                allow_trace_collapse=True,
                interim_text=interim_text,
            )
        if execution_mode in {ExecutionMode.ORCHESTRATION_UPDATE, ExecutionMode.EXPLORE_TASK_RENDER}:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.COLLAPSIBLE,
                allow_trace_collapse=True,
            )
        return TurnUXPlan()
