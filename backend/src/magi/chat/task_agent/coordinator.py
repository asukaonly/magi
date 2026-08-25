"""Execution coordination for chat task agents."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from magi.core.logger import get_logger
from magi.llm.streaming_events import LLMStreamEvent
from magi.skills.allowed_tools_rules import parse_allowed_tools
from magi.agent.execution.capability_resolver import CapabilityResolver
from magi.agent.task_agents.common import (
    CapabilitySelection,
    ExecutionHandlerRegistry,
    ExecutionRequest,
)
from magi.agent.task_agents.handlers.contracts import (
    ChatRuntimeContext,
    TurnAdmissionDecision,
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

logger = get_logger(__name__)


CapabilityTraceCallback = Callable[
    [ChatRuntimeContext, TurnAdmissionDecision, CapabilitySelection], Awaitable[None] | None
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
        capability_trace_callback: CapabilityTraceCallback | None = None,
        delivery_dispatcher: ChatDeliveryDispatchPort | None = None,
        conversation_log: Any | None = None,
        attachment_resolver: AttachmentResolverPort | None = None,
    ) -> None:
        self._fact_classifier = fact_classifier
        # Resolves managed attachment payloads when classifying a turn's
        # effective attachments. Chat wires a chat-backed resolver; the null
        # implementation keeps attachment-free runtimes independent of chat storage.
        self._attachment_resolver = attachment_resolver or NullAttachmentResolver()
        self._handler_registry = handler_registry
        self._agent_run_handler = agent_run_handler
        self._capability_trace_callback = capability_trace_callback
        self._delivery_dispatcher = delivery_dispatcher
        # When supplied, the conversation log records this run as a consumer
        # of visible messages so later retracts can propagate to dependents.
        self._conversation_log = conversation_log
        self._turn_admission_service = ChatTurnAdmissionService()
        self._capability_resolver = CapabilityResolver(tool_registry)

    async def admit_context(self, context: ChatRuntimeContext) -> TurnAdmissionDecision:
        return self._turn_admission_service.resolve(context)

    async def resolve_capabilities(
        self,
        context: ChatRuntimeContext,
        admission: TurnAdmissionDecision,
    ) -> CapabilitySelection:
        if admission.execution_mode is not None:
            return CapabilitySelection(reasoning=admission.reasoning)
        resolution = self._capability_resolver.resolve(
            pinned_tools=_inline_skill_tools(context),
            required_tools=_attachment_resolver_tools(context),
            recent_tool_errors=context.recent_tool_errors,
            model_supports_tool_calls=context.core_model_supports_tool_calls,
        )
        admission.capability_resolution = resolution
        admission.tools = list(resolution.initial_exposed_tools)
        capabilities = CapabilitySelection(
            tools=list(resolution.initial_exposed_tools),
            reasoning="Stable resident, explicit, attachment, and continuity capabilities.",
        )
        if self._capability_trace_callback is not None:
            callback_result = self._capability_trace_callback(context, admission, capabilities)
            if inspect.isawaitable(callback_result):
                await callback_result
        return capabilities

    async def build_execution_request(
        self,
        context: ChatRuntimeContext,
        admission: TurnAdmissionDecision,
        capabilities: CapabilitySelection,
    ) -> ExecutionRequest:
        request = ExecutionRequest(
            mode=admission.execution_mode,
            context=context,
            admission=admission,
            capabilities=capabilities,
        )
        handler = self._resolve_handler(admission.execution_mode)
        return await handler.build_request(request)

    async def execute_request(self, request: ExecutionRequest):
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
                        revision=int(getattr(request.context, "session_run_revision", 0) or 0),
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
    return list(
        dict.fromkeys(rule.tool for rule in parse_allowed_tools(invocation.get("allowed_tools")))
    )
