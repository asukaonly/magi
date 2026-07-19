"""Execution coordination for chat task agents."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from magi.core.logger import get_logger
from magi.llm.streaming_events import LLMStreamEvent
from magi.tools.context_decider import ContextDecider
from magi.agent.task_agents.common import (
    ExecutionHandlerRegistry,
    ExecutionRequest,
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
from magi.delivery.contracts import DeliveryFanoutResult
from .delivery_dispatch import ChatDeliveryDispatchPort
from .fact_classifier import ChatFactClassifier
from .intent_resolution_service import ChatIntentResolutionService
from magi.agent.response_rhythm import strip_segmentation_sentinel
from .run_placement_service import ChatBackgroundLaunchRequest, ChatRunPlacementService
from .tool_selection_service import ChatToolSelectionService, ToolAdvisoryProvider
from .turn_ux_planner import TurnUXPlanner

logger = get_logger(__name__)


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
        run_placement_service: ChatRunPlacementService | None = None,
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
        self._intent_resolution_service = ChatIntentResolutionService(
            context_decider=context_decider,
            tool_selection_service=self._tool_selection_service,
            attachment_resolver=self._attachment_resolver,
            turn_route_resolver=self._turn_route_resolver,
            turn_ux_planner=self._turn_ux_planner,
        )
        self._run_placement_service = run_placement_service or ChatRunPlacementService()
        self._execution_engine = execution_engine or TaskAgentExecutionEngine(
            handler_registry=handler_registry,
            tool_registry=tool_registry,
            snapshot_store=session_run_store,
        )

    async def match_intent(self, context: ChatRuntimeContext) -> IntentDecision:
        intent_decision = self._intent_resolution_service.resolve_system_fact_intent(context)
        if intent_decision is None:
            intent_decision = await self._intent_resolution_service.resolve_user_intent(
                context,
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
        background_request = await (
            self._run_placement_service.maybe_prepare_background_launch(request)
        )
        if background_request is not None:
            return background_request
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

        if isinstance(request, ChatBackgroundLaunchRequest):
            background_result = await self._run_placement_service.launch_background(request)
            if background_result is not None:
                return background_result
            handler = self._handler_registry.get(request.mode)
            request = await handler.build_request(request)

        execution_outcome = await self._execution_engine.execute(request)
        # Final channel delivery belongs to chat post-processing. That seam runs
        # only after the matching chat outcome is durable, so an interrupted
        # execution cannot send an external reply that has no local record.
        return execution_outcome.result

    async def _fanout_to_origin_channels(
        self,
        request: ExecutionRequest,
        *,
        response_text: str,
        attachments=(),
        content: DeliveryContent | None = None,
        exclude_chat_sse: bool = False,
        exclude_channel_types: Iterable[str] = (),
    ) -> DeliveryFanoutResult:
        """Deliver a final assistant response to the user's configured +
        originating delivery channels.

        Chat post-processing uses this for every execution path, including
        worker and explore results, so a durable reply reaches both the desktop
        surface and its originating external channel. No-op when no delivery
        dispatcher is wired.

        Final responses are delivered from the postprocess seam after the chat
        outcome is durable. ``exclude_chat_sse=True`` is used for streamed turns:
        chat_sse already received chunks, while non-streaming external channels
        still need the assembled final response.
        ``content`` overrides the default bare-text DeliveryContent when supplied.
        Returns the DeliveryReceipts so callers can chain if needed (receipts are
        also persisted here as before).
        """
        if self._delivery_dispatcher is None:
            return DeliveryFanoutResult()
        response_text = strip_segmentation_sentinel(response_text)
        if content is not None and content.text != response_text:
            content = replace(content, text=response_text)
        delivery_kwargs: dict[str, Any] = {
            "response_text": response_text,
            "attachments": attachments,
            "content": content,
            "exclude_chat_sse": exclude_chat_sse,
        }
        excluded_channel_types = tuple(exclude_channel_types)
        if excluded_channel_types:
            delivery_kwargs["exclude_channel_types"] = excluded_channel_types
        return await self._delivery_dispatcher.deliver_final_response(
            request,
            **delivery_kwargs,
        )

    async def deliver_final_chat_response(
        self,
        context,
        *,
        content: DeliveryContent,
        exclude_chat_sse: bool = False,
        exclude_channel_types: Iterable[str] = (),
    ) -> DeliveryFanoutResult:
        """Deliver one durable final chat response to its channel targets.

        Invoked from postprocess, where the persisted message identity and rich
        delivery metadata are available. Non-streamed turns fan out to every
        configured/origin channel. Streamed turns exclude chat_sse because its
        chunk stream already rendered the response there.

        ``context`` is the postprocess ``ChatRuntimeContext``; the fanout helper
        only reads ``request.context``, so a thin shim is sufficient.
        """
        request = SimpleNamespace(context=context)
        return await self._fanout_to_origin_channels(
            request,
            response_text=content.text,
            attachments=content.attachments,
            content=content,
            exclude_chat_sse=exclude_chat_sse,
            exclude_channel_types=exclude_channel_types,
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
