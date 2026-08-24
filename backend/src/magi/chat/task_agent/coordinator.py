"""Execution coordination for chat task agents."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from magi.core.logger import get_logger
from magi.llm.streaming_events import LLMStreamEvent
from magi.agent.execution.capability_resolver import CapabilityResolver
from magi.agent.task_agents.common import (
    ExecutionHandlerRegistry,
    ExecutionRequest,
    ToolSelection,
)
from magi.agent.task_agents.handlers.contracts import (
    ChatRuntimeContext,
    IntentDecision,
)
from magi_plugin_sdk.delivery import DeliveryContent
from magi.agent.execution.attachment_resolver import (
    AttachmentResolverPort,
    NullAttachmentResolver,
)
from magi.delivery.contracts import DeliveryFanoutResult
from .delivery_dispatch import ChatDeliveryDispatchPort
from .fact_classifier import ChatFactClassifier
from .turn_admission_service import ChatTurnAdmissionService
from magi.agent.response_rhythm import strip_segmentation_sentinel

ToolAdvisoryProvider = Callable[
    [str | None, list[str] | None, int], Awaitable[list[dict[str, Any]]]
]

logger = get_logger(__name__)


ToolSelectionTraceCallback = Callable[
    [ChatRuntimeContext, IntentDecision, ToolSelection], Awaitable[None] | None
]


class ChatExecutionCoordinator:
    """Admit domain facts and build one unified model-facing run."""

    def __init__(
        self,
        *,
        tool_registry: Any,
        fact_classifier: ChatFactClassifier,
        handler_registry: ExecutionHandlerRegistry,
        agent_run_handler: Any,
        tool_advisory_provider: ToolAdvisoryProvider | None = None,
        tool_selection_trace_callback: ToolSelectionTraceCallback | None = None,
        delivery_dispatcher: ChatDeliveryDispatchPort | None = None,
        conversation_log: Any | None = None,
        attachment_resolver: AttachmentResolverPort | None = None,
    ) -> None:
        self._fact_classifier = fact_classifier
        # Resolves managed attachment payloads when classifying a turn's
        # effective attachments. Chat wires a chat-backed resolver; defaults
        # to a null resolver for legacy / test callers.
        self._attachment_resolver = attachment_resolver or NullAttachmentResolver()
        self._handler_registry = handler_registry
        self._agent_run_handler = agent_run_handler
        self._tool_selection_trace_callback = tool_selection_trace_callback
        self._delivery_dispatcher = delivery_dispatcher
        # Phase F Task 10: optional ConversationLog. When supplied,
        # ``execute()`` records this run as a consumer of the currently
        # visible message_ids so a later cross-run retract (Task 11) can
        # propagate via ``ConversationLog.find_dependents``. None for
        # legacy callers / tests — recording is silently skipped.
        self._conversation_log = conversation_log
        self._tool_advisory_provider = tool_advisory_provider
        self._turn_admission_service = ChatTurnAdmissionService()
        self._capability_resolver = CapabilityResolver(tool_registry)

    async def match_intent(self, context: ChatRuntimeContext) -> IntentDecision:
        return self._turn_admission_service.resolve(context)

    async def match_tools(
        self, context: ChatRuntimeContext, intent: IntentDecision
    ) -> ToolSelection:
        if intent.execution_mode is not None:
            return ToolSelection(reasoning=intent.reasoning)
        resolution = self._capability_resolver.resolve(
            user_message=context.latest_user_message,
            explicit_tools=_inline_skill_tools(context),
            attachment_tools=_attachment_resolver_tools(context),
            recent_tool_errors=context.recent_tool_errors,
            model_supports_tool_calls=context.core_model_supports_tool_calls,
        )
        advisories = await self._load_capability_advisories(
            context.latest_user_message,
            list(resolution.initial_exposed_tools),
        )
        resolution = _rerank_capability_resolution(resolution, advisories)
        intent.capability_resolution = resolution
        intent.tools = list(resolution.initial_exposed_tools)
        intent.recommended_tools = list(advisories)
        tool_selection = ToolSelection(
            tools=list(resolution.initial_exposed_tools),
            reasoning="Deterministic resident, continuity, and metadata discovery.",
        )
        if self._tool_selection_trace_callback is not None:
            callback_result = self._tool_selection_trace_callback(context, intent, tool_selection)
            if inspect.isawaitable(callback_result):
                await callback_result
        return tool_selection

    async def _load_capability_advisories(
        self,
        user_message: str,
        tool_names: list[str],
    ) -> list[dict[str, Any]]:
        if self._tool_advisory_provider is None or not tool_names:
            return []
        try:
            return list(
                await self._tool_advisory_provider(
                    user_message,
                    tool_names,
                    len(tool_names),
                )
            )
        except Exception as exc:
            logger.debug("Capability advisory lookup failed: %s", exc)
            return []

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
        handler = self._resolve_handler(intent.execution_mode)
        return await handler.build_request(request)

    async def execute(self, request: ExecutionRequest):
        session_id = getattr(getattr(request, "context", None), "session_id", "") or ""
        session_run_id = getattr(getattr(request, "context", None), "session_run_id", "") or ""

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
        handler = self._resolve_handler(request.mode)
        execution_outcome = await handler.execute(request)
        # Final channel delivery belongs to chat post-processing. That seam runs
        # only after the matching chat outcome is durable, so an interrupted
        # execution cannot send an external reply that has no local record.
        return execution_outcome

    def _resolve_handler(self, mode: Any) -> Any:
        if mode is None:
            return self._agent_run_handler
        return self._handler_registry.get(mode)

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


def _attachment_resolver_tools(context: ChatRuntimeContext) -> list[str]:
    """Pin tools required to resolve current or explicitly replied-to assets."""

    names: list[str] = []

    def collect(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("resolver_tool") or "").strip()
            if name and name not in names:
                names.append(name)

    latest_payload = getattr(context, "latest_payload", None)
    collect(getattr(latest_payload, "attachments", None))
    reply_context = getattr(context, "reply_context", None)
    if bool(getattr(reply_context, "is_explicit_reply", False)):
        payload = getattr(reply_context, "structured_payload", None)
        if isinstance(payload, dict):
            collect(payload.get("asset_refs"))
            collect(payload.get("attachments"))
    return names


def _inline_skill_tools(context: ChatRuntimeContext) -> list[str]:
    payload = getattr(context, "latest_payload", None)
    invocation = getattr(payload, "skill_invocation", None)
    if not isinstance(invocation, dict):
        return []
    raw_tools = invocation.get("allowed_tools")
    if not isinstance(raw_tools, list):
        return []
    return list(
        dict.fromkeys(
            str(name).strip()
            for name in raw_tools
            if str(name).strip()
        )
    )


def _rerank_capability_resolution(resolution, advisories: list[dict[str, Any]]):
    """Rerank optional candidates without changing runtime authorization."""

    if not advisories:
        return resolution
    advisory_by_name = {
        str(item.get("tool_name") or item.get("name") or "").strip(): item
        for item in advisories
        if isinstance(item, dict)
    }
    required = list(
        dict.fromkeys(
            [*resolution.resident_tools, *resolution.continuity_pinned_tools]
            + list(resolution.pinned_tools)
        )
    )
    optional = [
        name for name in resolution.initial_exposed_tools if name not in required
    ]

    def rank(name: str) -> tuple[int, float, str]:
        advisory = advisory_by_name.get(name) or {}
        breaker = str(advisory.get("breaker_state") or "closed").strip().lower()
        success_rate = float(advisory.get("success_rate") or 0.0)
        return (0 if breaker == "closed" else 1, -success_rate, name)

    return replace(
        resolution,
        initial_exposed_tools=tuple([*required, *sorted(optional, key=rank)]),
    )
