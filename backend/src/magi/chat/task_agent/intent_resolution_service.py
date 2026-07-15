"""Intent resolution pipeline for chat task-agent turns."""

from __future__ import annotations

import os
import platform
from datetime import datetime
from typing import Any

from magi.agent.message_utils import build_recent_messages
from magi.agent.orchestration_plan import OrchestrationPlan
from magi.agent.run.ports import AttachmentResolverPort
from magi.agent.task_agents.common import ExecutionMode, IncomingFactKind
from magi.agent.task_agents.handlers.attachment_context import (
    resolve_effective_turn_attachments,
)
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.handlers.turn_route_resolver import (
    TurnRouteResolution,
    TurnRouteResolver,
)
from magi.config.models import ThinkingDepth
from magi.personality.active_persona import get_current_personality_config
from magi.personality.persona_routing_brief import build_persona_routing_brief
from magi.personality.turn_planner import PersonaRoutingHint
from magi.tools.context_decider import ContextDecider
from magi.tools.context_decider_context import ContextDeciderContext
from magi.tools.context_routing import should_decompose_external_request

from .tool_selection_service import ChatToolSelectionService
from .turn_ux_planner import TurnUXPlanner

_CODE_OR_LOCAL_REQUEST_HINTS = (
    "code",
    "codebase",
    "repo",
    "repository",
    "source",
    "file",
    "function",
    "class",
    "module",
    "stack trace",
    "traceback",
    "bug",
    "代码",
    "代码库",
    "仓库",
    "源码",
    "文件",
    "函数",
    "类",
    "模块",
    "报错",
    "调用链",
)


class ChatIntentResolutionService:
    """Resolve a chat runtime context into a typed intent decision."""

    def __init__(
        self,
        *,
        context_decider: ContextDecider,
        tool_selection_service: ChatToolSelectionService,
        attachment_resolver: AttachmentResolverPort,
        turn_route_resolver: TurnRouteResolver,
        turn_ux_planner: TurnUXPlanner,
    ) -> None:
        self._context_decider = context_decider
        self._tool_selection_service = tool_selection_service
        self._attachment_resolver = attachment_resolver
        self._turn_route_resolver = turn_route_resolver
        self._turn_ux_planner = turn_ux_planner

    def resolve_system_fact_intent(
        self,
        context: ChatRuntimeContext,
    ) -> IntentDecision | None:
        planner_fact_kind = _resolve_planner_fact_kind(context)
        if planner_fact_kind == IncomingFactKind.WORKER_UPDATE:
            return self._build_fixed_intent(
                context,
                intent="worker_orchestration_update",
                execution_mode=ExecutionMode.ORCHESTRATION_UPDATE,
                reasoning="Worker events must update orchestration state before any final response is emitted.",
            )
        if planner_fact_kind == IncomingFactKind.EXPLORE_TASK_COMPLETED:
            return self._build_fixed_intent(
                context,
                intent="explore_task_completed",
                execution_mode=ExecutionMode.EXPLORE_TASK_RENDER,
                reasoning="ExploreTaskAgent produced a Markdown dossier that must be rendered back to the user.",
            )
        if planner_fact_kind == IncomingFactKind.OTHER_FACT:
            return self._build_fixed_intent(
                context,
                intent="non_user_fact",
                execution_mode=ExecutionMode.FACT_ONLY,
                reasoning="Non-user fact does not require immediate LLM response.",
            )
        return None

    async def resolve_user_intent(self, context: ChatRuntimeContext) -> IntentDecision:
        if context.recall_feedback is not None:
            return self._build_fixed_intent(
                context,
                intent="recall_feedback_correction",
                execution_mode=ExecutionMode.DIRECT_LLM,
                reasoning=(
                    "Recall feedback is resolved from the targeted chat evidence before "
                    "normal routing so the feedback text cannot become a new memory query."
                ),
            )
        decision_context = await self._build_decider_context(context)
        decision = await self._context_decider.decide(
            context.latest_user_message,
            decision_context,
        )
        force_direct_external = _should_force_direct_external_plan(
            user_message=context.latest_user_message,
            orchestration_plan=OrchestrationPlan.from_route_decision(decision),
        )
        route_resolution = await self._resolve_route(
            context,
            decision=decision,
            force_direct_external=force_direct_external,
        )
        return self._build_intent_decision(
            context,
            decision=route_resolution.route_decision,
            selected_tools=list(route_resolution.selected_tools),
            execution_mode=route_resolution.execution_mode,
            orchestration_plan=route_resolution.orchestration_plan,
        )

    def _build_fixed_intent(
        self,
        context: ChatRuntimeContext,
        *,
        intent: str,
        execution_mode: ExecutionMode,
        reasoning: str,
    ) -> IntentDecision:
        return IntentDecision(
            intent=intent,
            difficulty="normal",
            execution_mode=execution_mode,
            reasoning=reasoning,
            ux_plan=self._turn_ux_planner.build(
                user_message=context.latest_user_message,
                execution_mode=execution_mode,
                tools=[],
                route_decision=None,
            ),
        )

    async def _build_decider_context(
        self,
        context: ChatRuntimeContext,
    ) -> ContextDeciderContext:
        now = datetime.now().astimezone()
        decision_context = ContextDeciderContext(
            os_name=platform.system(),
            os_version=platform.release(),
            current_datetime=now.isoformat(timespec="seconds"),
            timezone=str(now.tzinfo or "unknown"),
            workspace_path=str(getattr(context.latest_payload, "workspace_path", "") or ""),
            home_dir=os.path.expanduser("~"),
            current_user="unknown",
            recent_messages=build_recent_messages(
                context.history,
                limit=6,
                content_limit=120,
                exclude_latest_user_message=context.latest_user_message,
            ),
            recent_tool_errors=list(context.recent_tool_errors),
            recent_tool_state=list(context.recent_tool_state),
            persona_routing_brief=build_persona_routing_brief(
                get_current_personality_config(),
            ),
        )
        decision_context.tool_advisory = await (
            self._tool_selection_service.build_prompt_tool_advisory(
                user_message=context.latest_user_message,
            )
        )
        return decision_context

    async def _resolve_route(
        self,
        context: ChatRuntimeContext,
        *,
        decision: Any,
        force_direct_external: bool,
    ) -> TurnRouteResolution:
        effective_attachments = resolve_effective_turn_attachments(
            context,
            resolver=self._attachment_resolver,
        )
        has_image_attachments = _has_image_attachments(effective_attachments)
        route_resolution = self._turn_route_resolver.resolve_intent_route(
            user_message=context.latest_user_message,
            route_decision=decision,
            registered_tools=set(self._context_decider.tool_registry.list_tools()),
            effective_attachments=effective_attachments,
            force_direct_external=force_direct_external,
        )
        selected_tools = list(route_resolution.selected_tools)
        if not selected_tools:
            return route_resolution
        selected_tools = await self._tool_selection_service.rerank_selected_tools(
            task_context=context.latest_user_message,
            tool_names=selected_tools,
        )
        return self._turn_route_resolver.finalize_intent_route(
            route_decision=decision,
            selected_tools=selected_tools,
            has_image_attachments=has_image_attachments,
            force_direct_external=force_direct_external,
        )

    def _build_intent_decision(
        self,
        context: ChatRuntimeContext,
        *,
        decision: Any,
        selected_tools: list[str],
        execution_mode: ExecutionMode,
        orchestration_plan: OrchestrationPlan,
    ) -> IntentDecision:
        return IntentDecision(
            intent=decision.profile,
            difficulty=(
                "hard"
                if decision.thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW)
                else "normal"
            ),
            execution_mode=execution_mode,
            ux_plan=self._turn_ux_planner.build(
                user_message=context.latest_user_message,
                execution_mode=execution_mode,
                tools=selected_tools,
                route_decision=decision,
            ),
            tools=selected_tools,
            llm_trace=dict(getattr(decision, "llm_trace", {}) or {}),
            thinking_depth=decision.thinking_depth,
            reasoning=str(decision.reasoning),
            memory_route=str(getattr(decision, "memory_route", "none") or "none"),
            task_hint=self._tool_selection_service.resolve_runtime_task_hint(
                user_message=context.latest_user_message,
                selected_tools=selected_tools,
                execution_mode=execution_mode,
            ),
            persona_routing_hint=_build_persona_routing_hint(decision),
            route_decision=decision,
            orchestration_plan=orchestration_plan,
        )


def _resolve_planner_fact_kind(context: ChatRuntimeContext) -> IncomingFactKind:
    if context.planner_fact is not None or context.planner_fact_kind != IncomingFactKind.OTHER_FACT:
        return context.planner_fact_kind
    return context.incoming_fact_kind


def _has_image_attachments(effective_attachments: list[Any] | tuple[Any, ...]) -> bool:
    return any(
        isinstance(item, dict) and str(item.get("kind") or "").strip() == "image"
        for item in effective_attachments
    )


def _build_persona_routing_hint(decision: Any) -> PersonaRoutingHint | None:
    register = getattr(decision, "register", None)
    trigger_ids = tuple(getattr(decision, "active_trigger_ids", ()) or ())
    quiet_hints = tuple(getattr(decision, "quiet_hour_hints", ()) or ())
    situation_strength = str(getattr(decision, "situation_strength", "ordinary") or "ordinary")
    if not register and not trigger_ids and not quiet_hints and situation_strength == "ordinary":
        return None
    return PersonaRoutingHint(
        register=register if isinstance(register, str) and register else None,
        active_trigger_ids=trigger_ids,
        situation_strength=situation_strength,
        quiet_hour_hints=quiet_hints,
    )


def _should_force_direct_external_plan(
    *,
    user_message: str,
    orchestration_plan: OrchestrationPlan,
) -> bool:
    if orchestration_plan.mode != "decompose":
        return False
    if orchestration_plan.default_leaf_type != "general-purpose":
        return False
    user_lower = str(user_message or "").lower()
    if any(hint in user_lower for hint in _CODE_OR_LOCAL_REQUEST_HINTS):
        return False
    return not should_decompose_external_request(user_message)


__all__ = ["ChatIntentResolutionService"]
