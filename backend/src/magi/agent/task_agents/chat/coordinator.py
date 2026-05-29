"""Execution coordination for chat task agents."""

from __future__ import annotations

import dataclasses
import inspect
import os
import platform
import random
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List

from ....agent.message_utils import build_recent_messages
from ....config.models import ThinkingDepth
from ....core.logger import get_logger
from ....personality.active_persona import get_current_personality_config
from ....personality.persona_routing_brief import build_persona_routing_brief
from ....personality.turn_planner import PersonaRoutingHint
from ....tools.context_decider import ContextDecider
from ....tools.context_decider_context import ContextDeciderContext
from ....tools.context_routing import RouteDecision, should_decompose_external_request
from ....tools.recommender import ToolRecommender
from ....tools.schema import ToolExecutionContext
from ....tools.tool_advisory_reranker import ToolAdvisoryReranker
from ....tools.tool_hint_resolver import ToolHintResolver
from ..common import (
    ExecutionMode,
    ExecutionHandlerRegistry,
    ExecutionRequest,
    IncomingFactKind,
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
from ....channels.delivery_router import DeliveryRouter
from ....channels.delivery_prefs import resolve_delivery_targets
from magi_plugin_sdk.delivery import DeliveryContent
from ...run.builder import GraphBuilder
from ...run.nodes.plan_fanout import PlanFanoutNode
from ...run.nodes.reply import ReplyNode
from ...run.nodes.tool_loop import ToolLoopNode
from ...run.nodes.validate import ValidateNode
from ...run.registry import NodeRegistry
from ...run.runner import NodeSequenceRunner
from .attachment_context import resolve_effective_turn_attachments
from .fact_classifier import ChatFactClassifier

logger = get_logger(__name__)


def _build_persona_routing_hint(decision: Any) -> PersonaRoutingHint | None:
    """Lift the ContextDecider's per-persona routing fields into a hint.

    Returns ``None`` when the decision carries no persona-routing payload
    (rule-based fallback path, decider unavailable, or LLM omitted the
    fields). Downstream PersonaTurnPlanner falls back to its keyword
    classifier in that case.
    """
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


# Tools the execution LLM always has access to when tool-calling is active,
# regardless of what the Context Decider selected.  This avoids the routing
# LLM becoming a single point of failure for tool availability.
_FALLBACK_TOOLS = ["web-search", "find-relevant-tools"]
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

IntentTraceCallback = Callable[[ChatRuntimeContext, IntentDecision], Awaitable[None] | None]
ToolAdvisoryProvider = Callable[
    [str | None, list[str] | None, int], Awaitable[List[Dict[str, Any]]]
]
ToolSelectionTraceCallback = Callable[
    [ChatRuntimeContext, IntentDecision, ToolSelection], Awaitable[None] | None
]


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
        tool_selection_trace_callback: ToolSelectionTraceCallback | None = None,
        session_run_store: Any | None = None,
        channel_registry: Any | None = None,
    ) -> None:
        self._context_decider = context_decider
        self._fact_classifier = fact_classifier
        self._handler_registry = handler_registry
        self._intent_trace_callback = intent_trace_callback
        self._tool_advisory_provider = tool_advisory_provider
        self._tool_selection_trace_callback = tool_selection_trace_callback
        # Phase E: optional store for per-turn snapshot persistence.
        # When supplied, execute() calls run_with_snapshot and persists the
        # returned RunSnapshot so background-detached multi-node runs can
        # resume from the in-progress node. None for legacy / test callers.
        self._session_run_store = session_run_store
        # Phase G: DeliveryRouter for fanning out replies to user's
        # configured channels. Optional — if channel_registry is None,
        # delivery falls back to the legacy NotificationRelay path
        # (chat SSE only). This makes Phase G a strict additive change.
        self._delivery_router = (
            DeliveryRouter(channel_registry=channel_registry)
            if channel_registry is not None
            else None
        )
        tool_registry = getattr(context_decider, "tool_registry", None)
        self._tool_hint_resolver = (
            ToolHintResolver(tool_registry)
            if tool_registry is not None and callable(getattr(tool_registry, "get_tool", None))
            else None
        )
        self._tool_recommender = (
            ToolRecommender(tool_registry)
            if tool_registry is not None and callable(getattr(tool_registry, "get_tool", None))
            else None
        )
        self._tool_advisory_reranker = ToolAdvisoryReranker()
        # Phase C: parallel NodeRegistry for user-message paths keyed
        # by RouteDecision.graph_shape. The legacy handler_registry
        # remains responsible for non-route paths (ORCHESTRATION_UPDATE,
        # EXPLORE_TASK_RENDER, FACT_ONLY).
        self._node_registry = NodeRegistry()
        _direct_llm = handler_registry._handlers.get(ExecutionMode.DIRECT_LLM)
        _function_calling = handler_registry._handlers.get(ExecutionMode.FUNCTION_CALLING)
        _orchestration_launch = handler_registry._handlers.get(ExecutionMode.ORCHESTRATION_LAUNCH)
        if _direct_llm is not None:
            self._node_registry.register(ReplyNode(direct_llm_handler=_direct_llm))
        if _function_calling is not None:
            self._node_registry.register(ToolLoopNode(function_calling_handler=_function_calling))
        if _orchestration_launch is not None:
            self._node_registry.register(
                PlanFanoutNode(orchestration_launch_handler=_orchestration_launch)
            )
        # Phase D: ValidateNode runs verify tool after coding turns.
        # GraphBuilder + NodeSequenceRunner drive multi-node graphs.
        self._node_registry.register(
            ValidateNode(tool_registry=tool_registry)
        )
        self._graph_builder = GraphBuilder()
        self._node_sequence_runner = NodeSequenceRunner(
            node_registry=self._node_registry,
        )

    async def match_intent(self, context: ChatRuntimeContext) -> IntentDecision:
        planner_fact_kind = (
            context.planner_fact_kind
            if context.planner_fact is not None
            or context.planner_fact_kind != IncomingFactKind.OTHER_FACT
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
                    route_decision=None,
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
                    route_decision=None,
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
                    route_decision=None,
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
            persona_routing_brief=build_persona_routing_brief(get_current_personality_config()),
        )

        # Inject L4 procedural-memory advisory if provider is available.
        prompt_advisories: list[dict[str, Any]] = []
        if self._tool_advisory_provider is not None:
            try:
                prompt_advisories = await self._tool_advisory_provider(
                    context.latest_user_message,
                    None,
                    6,
                )
            except Exception as exc:
                logger.debug("Failed to fetch tool advisory: %s", exc)
                prompt_advisories = []
        decision_context.tool_advisory = self._tool_advisory_reranker.compress_for_prompt(
            advisories=prompt_advisories,
            limit=3,
        )

        decision = await self._context_decider.decide(context.latest_user_message, decision_context)
        force_direct_external = self._should_force_direct_external_plan(
            user_message=context.latest_user_message,
            strategy=decision.to_legacy_strategy_dict(),
        )
        effective_attachments = resolve_effective_turn_attachments(context)
        has_image_attachments = any(
            isinstance(item, dict) and str(item.get("kind") or "").strip() == "image"
            for item in effective_attachments
        )
        selected_tools = [] if has_image_attachments else list(decision.tools)
        if not has_image_attachments and force_direct_external:
            selected_tools = self._prefer_direct_external_tools(selected_tools)
        # Ensure fallback tools are always available when tool-assisted execution
        # is active.  The execution LLM is smarter than the routing LLM and can
        # decide on its own whether web-search is useful for the current task.
        if selected_tools:
            registered = set(self._context_decider.tool_registry.list_tools())
            for ft in _FALLBACK_TOOLS:
                if ft not in selected_tools and ft in registered:
                    selected_tools.append(ft)
            selected_tools = await self._rerank_selected_tools(
                task_context=context.latest_user_message,
                tool_names=selected_tools,
            )

        # === Single source of truth for the per-turn dispatch ===
        # Both axes (request shape via execution_mode AND node selection via
        # GraphBuilder→graph_shape) must agree, otherwise we land in cases
        # like graph_shape='reply' + FunctionCallingRequest → ReplyNode →
        # DirectLLMHandler.execute() → AttributeError on .messages.
        #
        # Algorithm: compute an effective_graph_shape that folds in the two
        # overrides (image attachments → reply; force_direct_external on
        # plan_fanout → tool_loop or reply), derive execution_mode 1:1 from
        # that, then rewrite ``decision`` so downstream consumers (GraphBuilder,
        # IntentDecision.route_decision) see the same coerced value.
        if has_image_attachments:
            effective_graph_shape: str = "reply"
        elif decision.graph_shape == "plan_fanout" and force_direct_external:
            effective_graph_shape = "tool_loop" if selected_tools else "reply"
        elif decision.graph_shape == "tool_loop" and not selected_tools:
            # Empty tools + tool_loop has nothing to loop over; downgrade.
            effective_graph_shape = "reply"
        else:
            effective_graph_shape = decision.graph_shape

        if effective_graph_shape == "reply":
            # Tools are meaningless without a tool loop — the model can't
            # invoke them in a single-shot reply. Drop them so they don't
            # accidentally pull execution_mode back to FUNCTION_CALLING via
            # any future code path.
            selected_tools = []

        if effective_graph_shape != decision.graph_shape:
            decision = dataclasses.replace(decision, graph_shape=effective_graph_shape)

        if effective_graph_shape == "plan_fanout":
            execution_mode = ExecutionMode.ORCHESTRATION_LAUNCH
        elif effective_graph_shape == "tool_loop":
            execution_mode = ExecutionMode.FUNCTION_CALLING
        else:  # "reply"
            execution_mode = ExecutionMode.DIRECT_LLM
        persona_routing_hint = _build_persona_routing_hint(decision)
        intent_decision = IntentDecision(
            intent=decision.profile,  # RouteDecision uses profile as the intent label
            difficulty=(
                "hard"
                if decision.thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW)
                else "normal"
            ),
            execution_mode=execution_mode,
            ux_plan=self._build_turn_ux_plan(
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
            task_hint=self._resolve_runtime_task_hint(
                user_message=context.latest_user_message,
                selected_tools=selected_tools,
                execution_mode=execution_mode,
            ),
            persona_routing_hint=persona_routing_hint,
            route_decision=decision,
        )
        if self._intent_trace_callback is not None:
            callback_result = self._intent_trace_callback(context, intent_decision)
            if inspect.isawaitable(callback_result):
                await callback_result
        return intent_decision

    async def match_tools(
        self, context: ChatRuntimeContext, intent: IntentDecision
    ) -> ToolSelection:
        if intent.execution_mode in {
            ExecutionMode.ORCHESTRATION_LAUNCH,
            ExecutionMode.ORCHESTRATION_UPDATE,
            ExecutionMode.FACT_ONLY,
            ExecutionMode.EXPLORE_TASK_RENDER,
        }:
            return ToolSelection(
                tools=[], reasoning=intent.reasoning, task_hint=dict(intent.task_hint or {})
            )

        recommendations = self._recommend_runtime_tools(context=context, intent=intent)
        if recommendations:
            recommendations = await self._rerank_runtime_recommendations(
                task_context=context.latest_user_message,
                recommendations=recommendations,
            )
        recommended_names = [
            str(item.get("tool") or "").strip()
            for item in recommendations
            if str(item.get("tool") or "").strip()
        ]
        ordered_tools = recommended_names + [
            tool for tool in intent.tools if tool not in recommended_names
        ]
        tool_selection = ToolSelection(
            tools=ordered_tools,
            reasoning=intent.reasoning,
            task_hint=dict(intent.task_hint or {}),
            recommended_tools=recommendations,
        )
        intent.recommended_tools = list(recommendations)
        if self._tool_selection_trace_callback is not None:
            callback_result = self._tool_selection_trace_callback(context, intent, tool_selection)
            if inspect.isawaitable(callback_result):
                await callback_result
        return tool_selection

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
        # Phase D/E: build node sequence from RouteDecision (profile-aware:
        # coding profile auto-appends ValidateNode). Run via the
        # NodeSequenceRunner which handles single-node AND multi-node
        # graphs uniformly. Non-route paths fall through to the legacy
        # ExecutionHandlerRegistry.
        # Phase E: use run_with_snapshot so per-node state is persisted for
        # background-detached runs that need to resume from an in-progress node.
        route_decision = getattr(request.intent, "route_decision", None)
        if route_decision is not None:
            node_specs = self._graph_builder.build_node_sequence(route_decision)
            session_id = getattr(getattr(request, "context", None), "session_id", "") or ""
            session_run_id = getattr(getattr(request, "context", None), "session_run_id", "") or ""

            # Look for a resume snapshot — populated when a background
            # dispatcher rehydrates a detached run.
            resume_from = None
            if session_id and session_run_id and self._session_run_store is not None:
                stored_snapshot = self._session_run_store.get_run_snapshot(session_id, session_run_id)
                # Only resume from a partial snapshot. A completed snapshot
                # (cursor >= len(node_specs)) means the prior run finished;
                # using it would cause the runner's for-loop to be empty and
                # return "(no output)". Clear it so the next turn runs fresh.
                if stored_snapshot is not None and stored_snapshot.cursor < len(node_specs):
                    resume_from = stored_snapshot
                elif stored_snapshot is not None:
                    # Completed snapshot from a prior turn — discard.
                    self._session_run_store.clear_run_snapshot(session_id, session_run_id)

            runner_result, snapshot = await self._node_sequence_runner.run_with_snapshot(
                run_id=session_run_id or "",
                node_specs=node_specs,
                request=request,
                resume_from=resume_from,
            )

            # Persist the new snapshot so subsequent detach paths can read it.
            if session_id and session_run_id and self._session_run_store is not None:
                self._session_run_store.save_run_snapshot(session_id, session_run_id, snapshot)

            # Phase G: fan out the runner result to user's configured
            # delivery channels (when wired). Receipts are persisted on
            # the snapshot's node_states for later retract.
            if runner_result is not None and self._delivery_router is not None:
                user_prefs = getattr(request.context, "user_prefs", {}) or {}
                user_id = getattr(request.context, "user_id", "") or ""
                targets = resolve_delivery_targets(
                    user_id=user_id, session_id=session_id or "", user_prefs=user_prefs,
                )
                if targets:
                    content = DeliveryContent(text=runner_result.response_text or "")
                    receipts = await self._delivery_router.fanout_deliver(
                        content=content, targets=targets,
                    )
                    # Persist receipts on the snapshot so
                    # SessionRunCoordinator.request_retract can find + replay them.
                    if receipts and session_id and session_run_id and self._session_run_store is not None:
                        receipt_payloads = [r.to_dict() for r in receipts]
                        self._session_run_store.save_run_snapshot(
                            session_id, session_run_id,
                            _attach_receipts(snapshot, receipt_payloads),
                        )

            if runner_result is not None:
                return runner_result
        handler = self._handler_registry.get(request.mode)
        return await handler.execute(request)

    async def dispatch_stream_chunk(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        is_final: bool,
        seq: int,
    ) -> None:
        """Stream one chunk to every configured channel for this user/session.

        No-op when no delivery router is wired (legacy / test paths) or
        session_id is empty. Errors per channel are isolated inside
        DeliveryRouter.fanout_chunk.
        """
        if self._delivery_router is None or not session_id:
            return
        from magi_plugin_sdk.delivery import DeliveryChunk
        targets = resolve_delivery_targets(
            user_id=user_id, session_id=session_id, user_prefs={},
        )
        await self._delivery_router.fanout_chunk(
            chunk=DeliveryChunk(text=text, is_final=is_final, seq=seq),
            targets=targets,
        )

    @staticmethod
    def _should_force_direct_external_plan(
        *,
        user_message: str,
        strategy: dict[str, Any] | None,
    ) -> bool:
        if not isinstance(strategy, dict):
            return False
        if str(strategy.get("mode") or "").strip() != "decompose":
            return False
        if str(strategy.get("default_leaf_type") or "").strip() != "general-purpose":
            return False
        user_lower = str(user_message or "").lower()
        if any(hint in user_lower for hint in _CODE_OR_LOCAL_REQUEST_HINTS):
            return False
        return not should_decompose_external_request(user_message)

    def _prefer_direct_external_tools(self, selected_tools: list[str]) -> list[str]:
        registered = set(self._context_decider.tool_registry.list_tools())
        direct_tools = [tool for tool in selected_tools if tool != "agent"]
        if "web-search" in registered and "web-search" not in direct_tools:
            direct_tools.append("web-search")
        if (
            "web-fetch" in selected_tools
            and "web-fetch" in registered
            and "web-fetch" not in direct_tools
        ):
            direct_tools.append("web-fetch")
        return direct_tools

    def _resolve_runtime_task_hint(
        self,
        *,
        user_message: str,
        selected_tools: list[str],
        execution_mode: ExecutionMode,
    ) -> dict[str, Any]:
        if self._tool_hint_resolver is None or not selected_tools:
            return {}
        request_profile = (
            "research"
            if any(tool in {"web-search", "web-fetch"} for tool in selected_tools)
            else None
        )
        scope_hints: list[str] = []
        if any(
            marker in user_message
            for marker in ["~/", "/", "\\", "src/", "backend/", "frontend/", "docs/"]
        ):
            scope_hints.append("The request references an explicit path or subdirectory.")
        if execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH:
            scope_hints.append("The request will be decomposed into orchestration work.")
        return self._tool_hint_resolver.resolve(
            user_message=user_message,
            available_tools=list(selected_tools),
            request_profile=request_profile,
            scope_hints=scope_hints,
        )

    def _recommend_runtime_tools(
        self, *, context: ChatRuntimeContext, intent: IntentDecision
    ) -> list[dict[str, Any]]:
        if self._tool_recommender is None or not intent.tools:
            return []
        try:
            execution_context = ToolExecutionContext(
                agent_id=context.agent_id,
                workspace=str(getattr(context.latest_payload, "workspace_path", "") or "."),
                permissions=["authenticated", "dangerous_tools"],
                env_vars={"session_id": context.session_id, "user_id": context.user_id},
            )
            return self._tool_recommender.recommend_tools(
                intent=context.latest_user_message,
                context=execution_context,
                top_k=len(intent.tools),
                task_hint=intent.task_hint,
                candidate_tools=list(intent.tools),
            )
        except Exception as exc:
            logger.debug(
                "Runtime tool recommendation failed, falling back to router order: %s", exc
            )
            return []

    async def _rerank_selected_tools(
        self,
        *,
        task_context: str,
        tool_names: list[str],
    ) -> list[str]:
        if self._tool_advisory_provider is None or not tool_names:
            return tool_names
        try:
            advisories = await self._tool_advisory_provider(
                task_context,
                list(tool_names),
                len(tool_names),
            )
        except Exception as exc:
            logger.debug("Failed to fetch targeted tool advisory: %s", exc)
            return tool_names
        return self._tool_advisory_reranker.rerank_tool_names(
            tool_names=tool_names,
            advisories=advisories,
        )

    async def _rerank_runtime_recommendations(
        self,
        *,
        task_context: str,
        recommendations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self._tool_advisory_provider is None or not recommendations:
            return recommendations
        tool_names = [
            str(item.get("tool") or item.get("name") or "").strip()
            for item in recommendations
            if str(item.get("tool") or item.get("name") or "").strip()
        ]
        if not tool_names:
            return recommendations
        try:
            advisories = await self._tool_advisory_provider(
                task_context,
                tool_names,
                len(tool_names),
            )
        except Exception as exc:
            logger.debug("Failed to fetch runtime recommendation advisory: %s", exc)
            return recommendations
        return self._tool_advisory_reranker.rerank_recommendations(
            recommendations=recommendations,
            advisories=advisories,
        )

    def _build_turn_ux_plan(
        self,
        *,
        user_message: str,
        execution_mode: ExecutionMode,
        tools: list[str],
        route_decision: RouteDecision | None = None,
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
                trace_display_mode=TraceDisplayMode.COLLAPSIBLE,
            )
        if execution_mode == ExecutionMode.FUNCTION_CALLING:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.PROMINENT,
                allow_trace_collapse=bool(tools),
            )
        if execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH:
            is_explore = bool(
                route_decision is not None
                and route_decision.profile == "explore"
                and route_decision.graph_shape == "plan_fanout"
            )
            interim_text = self._resolve_interim_text(
                mode_key="explore_task" if is_explore else "orchestration_launch",
                user_message=user_message,
            )
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.INTERIM_THEN_FINAL,
                thinking_indicator=ThinkingIndicatorMode.SUBTLE,
                trace_display_mode=TraceDisplayMode.PROMINENT,
                allow_trace_collapse=True,
                interim_text=interim_text,
            )
        if execution_mode in {
            ExecutionMode.ORCHESTRATION_UPDATE,
            ExecutionMode.EXPLORE_TASK_RENDER,
        }:
            return TurnUXPlan(
                assistant_surface_mode=AssistantSurfaceMode.FINAL_ONLY,
                thinking_indicator=ThinkingIndicatorMode.HIDDEN,
                trace_display_mode=TraceDisplayMode.PROMINENT,
                allow_trace_collapse=True,
            )
        return TurnUXPlan()

    # -- interim-text resolution -------------------------------------------------

    _INTERIM_FALLBACK_LINES: Dict[str, Dict[str, List[str]]] = {
        "zh": {
            "orchestration_launch": ["让我仔细想想再回复你。"],
            "explore_task": ["我去仔细看一下，稍后把结果给你。"],
        },
        "en": {
            "orchestration_launch": ["Let me think this through and check for you."],
            "explore_task": ["Let me inspect this in detail and I will come back with the result."],
        },
    }

    @staticmethod
    def _detect_message_language(message: str) -> str:
        """Return ``"zh"`` if the message contains CJK, otherwise ``"en"``."""
        for ch in message or "":
            # CJK Unified Ideographs block; sufficient for mandarin-leaning UX.
            if "\u4e00" <= ch <= "\u9fff":
                return "zh"
        return "en"

    def _resolve_interim_text(self, *, mode_key: str, user_message: str) -> str:
        """Pick the interim placeholder line for the active persona.

        Resolution order:

        1. ``interim_lines[mode_key]`` on the active ``PersonalityConfig``.
        2. ``interim_lines[mode_key]`` defaults for the user's message
           language (zh / en).
        3. Generic English fallback (never empty).

        When a key maps to multiple candidate lines one is chosen at random
        so the bubble does not feel copy-pasted across turns.
        """
        persona_config = None
        try:
            persona_config = get_current_personality_config()
        except Exception:  # pragma: no cover - defensive, persona cache should never raise
            persona_config = None
        persona_lines: List[str] = []
        if persona_config is not None:
            persona_lines = list(getattr(persona_config, "interim_lines", {}).get(mode_key, []))
        if persona_lines:
            return random.choice(persona_lines)
        lang = self._detect_message_language(user_message)
        fallback = self._INTERIM_FALLBACK_LINES.get(lang, {}).get(mode_key)
        if fallback:
            return random.choice(fallback)
        # Ultimate safety net: English orchestration_launch line. Keeps the
        # UI contract that interim_text is always a non-empty string.
        return self._INTERIM_FALLBACK_LINES["en"]["orchestration_launch"][0]


def _attach_receipts(snapshot, receipt_payloads):
    """Phase G: attach delivery receipts to the last completed node's state.

    Stores the receipt list under ``node_states[last_node_type]["delivery_receipts"]``
    so ``SessionRunCoordinator.request_retract`` can reconstruct them from the
    snapshot and call ``DeliveryRouter.fanout_retract``.
    """
    import dataclasses
    if not snapshot.graph or snapshot.cursor == 0:
        return snapshot
    last_node_type = snapshot.graph[min(snapshot.cursor, len(snapshot.graph)) - 1]
    updated_node_states = dict(snapshot.node_states)
    last_state = dict(updated_node_states.get(last_node_type, {}))
    last_state["delivery_receipts"] = receipt_payloads
    updated_node_states[last_node_type] = last_state
    return dataclasses.replace(snapshot, node_states=updated_node_states)
