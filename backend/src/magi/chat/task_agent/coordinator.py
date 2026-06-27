"""Execution coordination for chat task agents."""

from __future__ import annotations

import dataclasses
import inspect
import os
import platform
import random
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List

from magi.agent.message_utils import build_recent_messages
from magi.config.models import ThinkingDepth
from magi.core.logger import get_logger
from magi.llm.streaming_events import LLMStreamEvent
from magi.personality.active_persona import get_current_personality_config
from magi.personality.persona_routing_brief import build_persona_routing_brief
from magi.personality.turn_planner import PersonaRoutingHint
from magi.tools.context_decider import ContextDecider
from magi.tools.context_decider_context import ContextDeciderContext
from magi.tools.context_routing import RouteDecision, should_decompose_external_request
from magi.tools.recommender import ToolRecommender
from magi.tools.schema import ToolExecutionContext
from magi.tools.tool_advisory_reranker import ToolAdvisoryReranker
from magi.tools.tool_hint_resolver import ToolHintResolver
from magi.tools.capabilities import build_tool_capabilities
from magi.chat.task_agent.execution_shape import derive_execution_shape
from magi.agent.task_agents.common import (
    ExecutionMode,
    ExecutionHandlerRegistry,
    ExecutionRequest,
    IncomingFactKind,
    ToolSelection,
)
from magi.agent.task_agents.handlers.contracts import (
    AssistantSurfaceMode,
    ChatRuntimeContext,
    IntentDecision,
    ThinkingIndicatorMode,
    TraceDisplayMode,
    TurnUXPlan,
)
from magi_plugin_sdk.delivery import DeliveryContent
from magi.agent.run.builder import GraphBuilder
from magi.agent.run.ports import AttachmentResolverPort, NullAttachmentResolver
from magi.agent.run.nodes.plan_fanout import PlanFanoutNode
from magi.agent.run.nodes.reply import ReplyNode
from magi.agent.run.nodes.tool_loop import ToolLoopNode
from magi.agent.run.nodes.validate import ValidateNode
from magi.agent.run.registry import NodeRegistry
from magi.agent.run.runner import NodeSequenceRunner
from magi.agent.task_agents.handlers.attachment_context import resolve_effective_turn_attachments
from .delivery_dispatch import ChatDeliveryDispatchPort
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
        delivery_dispatcher: ChatDeliveryDispatchPort | None = None,
        conversation_log: Any | None = None,
        attachment_resolver: AttachmentResolverPort | None = None,
    ) -> None:
        self._context_decider = context_decider
        self._fact_classifier = fact_classifier
        # Resolves managed attachment payloads when classifying a turn's
        # effective attachments. Chat wires a chat-backed resolver; defaults
        # to a null resolver for legacy / test callers.
        self._attachment_resolver = attachment_resolver or NullAttachmentResolver()
        self._handler_registry = handler_registry
        self._intent_trace_callback = intent_trace_callback
        self._tool_advisory_provider = tool_advisory_provider
        self._tool_selection_trace_callback = tool_selection_trace_callback
        # Phase E: optional store for per-turn snapshot persistence.
        # When supplied, execute() calls run_with_snapshot and persists the
        # returned RunSnapshot so background-detached multi-node runs can
        # resume from the in-progress node. None for legacy / test callers.
        self._session_run_store = session_run_store
        self._delivery_dispatcher = delivery_dispatcher
        # Phase F Task 10: optional ConversationLog. When supplied,
        # ``execute()`` records this run as a consumer of the currently
        # visible message_ids so a later cross-run retract (Task 11) can
        # propagate via ``ConversationLog.find_dependents``. None for
        # legacy callers / tests — recording is silently skipped.
        self._conversation_log = conversation_log
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
        effective_attachments = resolve_effective_turn_attachments(
            context, resolver=self._attachment_resolver
        )
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

        # === Single source of truth for the per-turn dispatch (ADR-0005) ===
        # The execution shape is DERIVED from semantic signals, never an
        # independent LLM field that could contradict the tool list. This is
        # what makes "the router selected a tool but it got dropped" impossible:
        # a turn that selected tools derives to tool_loop, full stop.
        #
        # P3: the router emits a three-state needs_orchestration. A bounded
        # external request (force_direct_external) demotes a "required" fanout
        # down to a plain tool loop ("none"); "maybe" is preserved so the model
        # can self-escalate in-loop via the injected `agent` tool.
        orchestration = decision.needs_orchestration
        # Backward-compat: a decision that only set graph_shape="plan_fanout"
        # (older callers / direct construction that predate needs_orchestration)
        # maps to "required".
        if orchestration == "none" and decision.graph_shape == "plan_fanout":
            orchestration = "required"
        if force_direct_external and orchestration == "required":
            orchestration = "none"
        effective_graph_shape = derive_execution_shape(
            has_image_attachments=has_image_attachments,
            orchestration=orchestration,
            has_tools=bool(selected_tools),
        )

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

            # Phase F Task 10: tag this run as a consumer of the currently
            # visible history. ConversationLog.find_dependents reverses this
            # map for cross-run retract propagation (Task 11). Failures are
            # swallowed so a log outage never blocks execution — the cost
            # of a missed record is at worst a future retract that doesn't
            # propagate to this run.
            if self._conversation_log is not None and session_id and session_run_id:
                try:
                    message_ids = await self._conversation_log.list_visible_message_ids(
                        session_id=session_id,
                    )
                except Exception:
                    logger.warning(
                        "ConversationLog.list_visible_message_ids failed",
                        exc_info=True,
                    )
                    message_ids = []
                if message_ids:
                    try:
                        await self._conversation_log.record_consumed(
                            session_id=session_id,
                            run_id=session_run_id,
                            revision=int(
                                getattr(request.context, "session_run_revision", 0) or 0
                            ),
                            message_ids=message_ids,
                        )
                    except Exception:
                        logger.warning(
                            "ConversationLog.record_consumed failed",
                            exc_info=True,
                        )

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

            # Phase G: fan out the runner result to the user's configured +
            # originating delivery channels (when wired).
            if runner_result is not None:
                # P3 Step 3: execute()-time fanout serves EXTERNAL channels only;
                # the chat_sse agent_response is produced by the postprocess seam
                # (deliver_final_chat_response) with the full rich payload.
                await self._fanout_to_origin_channels(
                    request,
                    response_text=runner_result.response_text or "",
                    attachments=runner_result.attachments or (),
                    exclude_chat_sse=True,
                )
                return runner_result
        # Legacy handler-registry path (ORCHESTRATION_UPDATE worker results,
        # EXPLORE_TASK_RENDER, …). These also produce a final user-facing
        # response, so they must ALSO fan out to the originating external
        # channel — otherwise a WeChat/Telegram turn that got offloaded to a
        # worker subagent only reaches the message bus (desktop) and the
        # channel user hears nothing. Gated on a real, emit-worthy response so
        # interim worker progress (skip_emit / empty text) never spams the channel.
        handler = self._handler_registry.get(request.mode)
        result = await handler.execute(request)
        if getattr(result, "response_text", "") and not getattr(result, "skip_emit", False):
            # P3 Step 3: external channels only (chat_sse rich agent_response
            # comes from the postprocess seam).
            await self._fanout_to_origin_channels(
                request,
                response_text=result.response_text,
                attachments=getattr(result, "attachments", ()) or (),
                exclude_chat_sse=True,
            )
        return result

    async def _fanout_to_origin_channels(
        self,
        request: ExecutionRequest,
        *,
        response_text: str,
        attachments=(),
        content: DeliveryContent | None = None,
        exclude_chat_sse: bool = False,
        chat_sse_only: bool = False,
    ) -> list:
        """Deliver a final assistant response to the user's configured +
        originating delivery channels.

        Shared by the RouteDecision path (runner_result) and the legacy
        handler-registry path (ORCHESTRATION_UPDATE / EXPLORE_TASK_RENDER) so a
        turn that gets offloaded to a worker subagent reaches the originating
        external channel (WeChat/Telegram), not just the message bus. No-op when
        no delivery dispatcher is wired.

        P3 Step 3: the chat_sse ``agent_response`` and the external-channel
        delivery are split into two mutually-exclusive passes:
        - ``exclude_chat_sse=True`` (execute()-time fanout) → external channels
          only, for all turns; the bare text is delivered.
        - ``chat_sse_only=True`` (postprocess seam) → chat_sse only, carrying a
          pre-built rich ``DeliveryContent`` (turn_id/message_id/trace_summary/…).
        ``content`` overrides the default bare-text DeliveryContent when supplied.
        Returns the DeliveryReceipts so callers can chain if needed (receipts are
        also persisted here as before).
        """
        if self._delivery_dispatcher is None:
            return []
        return await self._delivery_dispatcher.deliver_final_response(
            request,
            response_text=response_text,
            attachments=attachments,
            content=content,
            exclude_chat_sse=exclude_chat_sse,
            chat_sse_only=chat_sse_only,
        )

    async def deliver_final_chat_response(
        self,
        context,
        *,
        content: DeliveryContent,
    ) -> list:
        """P3 Step 3: sole writer of the rich non-streamed chat_sse
        ``agent_response``. Invoked from postprocess (where message_id /
        trace_summary / ux_plan are finally known) with a fully-populated
        ``DeliveryContent``. Reuses the fanout target/prefs/origin/receipts
        machinery but restricts delivery to chat_sse — external channels are
        served by the execute()-time fanout (``exclude_chat_sse=True``), so no
        channel is double-served. No-op when no delivery dispatcher is wired.

        ``context`` is the postprocess ``ChatRuntimeContext``; the fanout helper
        only reads ``request.context``, so a thin shim is sufficient.
        """
        request = SimpleNamespace(context=context)
        return await self._fanout_to_origin_channels(
            request,
            response_text=content.text,
            attachments=content.attachments,
            content=content,
            chat_sse_only=True,
        )

    async def dispatch_stream_chunk(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        is_final: bool,
        seq: int,
        turn_id: str | None = None,
        event: LLMStreamEvent | None = None,
        persona_id: str | None = None,
    ) -> None:
        """Stream one chunk to every configured channel for this user/session.

        The injected dispatcher owns target resolution and preference lookup
        so streaming chunks reach the same delivery surface as final replies.
        No-op when no dispatcher is wired or session_id is empty.
        """
        if self._delivery_dispatcher is None or not session_id:
            return
        await self._delivery_dispatcher.dispatch_stream_chunk(
            session_id=session_id,
            user_id=user_id,
            text=text,
            is_final=is_final,
            seq=seq,
            turn_id=turn_id,
            event=event,
            persona_id=persona_id,
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
                capabilities=build_tool_capabilities(),
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
