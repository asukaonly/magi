"""Execution coordination for chat task agents."""

from __future__ import annotations

import inspect
import os
import platform
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from magi.agent.message_utils import build_recent_messages
from magi.agent.orchestration_plan import OrchestrationPlan
from magi.config.models import ThinkingDepth
from magi.core.logger import get_logger
from magi.llm.streaming_events import LLMStreamEvent
from magi.personality.active_persona import get_current_personality_config
from magi.personality.persona_routing_brief import build_persona_routing_brief
from magi.personality.turn_planner import PersonaRoutingHint
from magi.tools.context_decider import ContextDecider
from magi.tools.context_decider_context import ContextDeciderContext
from magi.tools.context_routing import should_decompose_external_request
from magi.agent.task_agents.common import (
    ExecutionMode,
    ExecutionHandlerRegistry,
    ExecutionRequest,
    IncomingFactKind,
    ToolSelection,
)
from magi.agent.task_agents.handlers.turn_route_resolver import TurnRouteResolver
from magi.agent.task_agents.handlers.contracts import (
    ChatRuntimeContext,
    IntentDecision,
)
from magi_plugin_sdk.delivery import DeliveryContent
from magi.agent.run.execution_engine import TaskAgentExecutionEngine
from magi.agent.run.ports import AttachmentResolverPort, NullAttachmentResolver
from magi.agent.task_agents.handlers.attachment_context import resolve_effective_turn_attachments
from .delivery_dispatch import ChatDeliveryDispatchPort
from .fact_classifier import ChatFactClassifier
from .rhythm import strip_segmentation_sentinel
from .tool_selection_service import ChatToolSelectionService, ToolAdvisoryProvider
from .turn_ux_planner import TurnUXPlanner

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
ToolSelectionTraceCallback = Callable[
    [ChatRuntimeContext, IntentDecision, ToolSelection], Awaitable[None] | None
]


class ChatExecutionCoordinator:
    """Coordinates intent routing, request building, and handler dispatch."""

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
        execution_engine: TaskAgentExecutionEngine | None = None,
    ) -> None:
        self._context_decider = context_decider
        self._fact_classifier = fact_classifier
        # Resolves managed attachment payloads when classifying a turn's
        # effective attachments. Chat wires a chat-backed resolver; defaults
        # to a null resolver for legacy / test callers.
        self._attachment_resolver = attachment_resolver or NullAttachmentResolver()
        self._handler_registry = handler_registry
        self._intent_trace_callback = intent_trace_callback
        self._tool_selection_trace_callback = tool_selection_trace_callback
        # Optional store handed to the agent execution engine for resumable
        # multi-step turns. None for legacy / test callers.
        self._session_run_store = session_run_store
        self._delivery_dispatcher = delivery_dispatcher
        # Phase F Task 10: optional ConversationLog. When supplied,
        # ``execute()`` records this run as a consumer of the currently
        # visible message_ids so a later cross-run retract (Task 11) can
        # propagate via ``ConversationLog.find_dependents``. None for
        # legacy callers / tests — recording is silently skipped.
        self._conversation_log = conversation_log
        tool_registry = getattr(context_decider, "tool_registry", None)
        self._tool_selection_service = ChatToolSelectionService(
            tool_registry=tool_registry,
            tool_advisory_provider=tool_advisory_provider,
        )
        self._turn_route_resolver = TurnRouteResolver()
        self._turn_ux_planner = TurnUXPlanner()
        self._execution_engine = execution_engine or TaskAgentExecutionEngine(
            handler_registry=handler_registry,
            tool_registry=tool_registry,
            snapshot_store=session_run_store,
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
                ux_plan=self._turn_ux_planner.build(
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
                ux_plan=self._turn_ux_planner.build(
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
                ux_plan=self._turn_ux_planner.build(
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

        decision_context.tool_advisory = await (
            self._tool_selection_service.build_prompt_tool_advisory(
                user_message=context.latest_user_message,
            )
        )

        decision = await self._context_decider.decide(context.latest_user_message, decision_context)
        proposed_plan = OrchestrationPlan.from_route_decision(decision)
        force_direct_external = self._should_force_direct_external_plan(
            user_message=context.latest_user_message,
            orchestration_plan=proposed_plan,
        )
        effective_attachments = resolve_effective_turn_attachments(
            context, resolver=self._attachment_resolver
        )
        has_image_attachments = any(
            isinstance(item, dict) and str(item.get("kind") or "").strip() == "image"
            for item in effective_attachments
        )
        registered_tools = set(self._context_decider.tool_registry.list_tools())
        route_resolution = self._turn_route_resolver.resolve_intent_route(
            user_message=context.latest_user_message,
            route_decision=decision,
            registered_tools=registered_tools,
            effective_attachments=effective_attachments,
            force_direct_external=force_direct_external,
        )
        selected_tools = list(route_resolution.selected_tools)
        if selected_tools:
            selected_tools = await self._tool_selection_service.rerank_selected_tools(
                task_context=context.latest_user_message,
                tool_names=selected_tools,
            )
            route_resolution = self._turn_route_resolver.finalize_intent_route(
                route_decision=decision,
                selected_tools=selected_tools,
                has_image_attachments=has_image_attachments,
                force_direct_external=force_direct_external,
            )

        decision = route_resolution.route_decision
        execution_mode = route_resolution.execution_mode
        orchestration_plan = route_resolution.orchestration_plan
        persona_routing_hint = _build_persona_routing_hint(decision)
        intent_decision = IntentDecision(
            intent=decision.profile,  # RouteDecision uses profile as the intent label
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
            persona_routing_hint=persona_routing_hint,
            route_decision=decision,
            orchestration_plan=orchestration_plan,
        )
        if self._intent_trace_callback is not None:
            callback_result = self._intent_trace_callback(context, intent_decision)
            if inspect.isawaitable(callback_result):
                await callback_result
        return intent_decision

    async def match_tools(
        self, context: ChatRuntimeContext, intent: IntentDecision
    ) -> ToolSelection:
        tool_selection = await self._tool_selection_service.select_tools(
            context=context,
            intent=intent,
        )
        intent.recommended_tools = list(tool_selection.recommended_tools)
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
        route_decision = getattr(request.intent, "route_decision", None)
        if route_decision is not None:
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

        execution_outcome = await self._execution_engine.execute(request)
        result = execution_outcome.result
        if result is None:
            return None
        if execution_outcome.used_graph:
            await self._fanout_to_origin_channels(
                request,
                response_text=result.response_text or "",
                attachments=getattr(result, "attachments", ()) or (),
                exclude_chat_sse=True,
            )
        elif getattr(result, "response_text", "") and not getattr(result, "skip_emit", False):
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
        response_text = strip_segmentation_sentinel(response_text)
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
