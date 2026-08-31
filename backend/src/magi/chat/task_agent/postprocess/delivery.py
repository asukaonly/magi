"""Final response delivery helpers for chat post-processing."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Protocol, cast

from magi_plugin_sdk.delivery import DeliveryContent

from magi.agent.task_agents.common import ExecutionResult
from magi.agent.task_agents.handlers.contracts import ChatParseOutcome, ChatRuntimeContext
from magi.delivery.contracts import DeliveryFanoutResult
from magi.core.logger import get_logger

from .final_response_plan import build_final_response_delivery_plan

logger = get_logger(__name__)


class _DeliveryPostprocessHostProtocol(Protocol):
    _chat_store: Any
    _deliver_final_response: Callable[..., Awaitable[DeliveryFanoutResult]] | None
    _runtime_notifier: Any

    async def _get_notification_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> Any | None: ...

    def _resolve_reaction_notification_text(
        self,
        ux_plan: dict[str, Any] | None,
        *,
        fallback: str,
    ) -> str: ...

    async def emit_execution_control_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        state: str,
        can_cancel: bool,
        label: str | None = None,
    ) -> None: ...


class _PreparedDeliveryStateProtocol(Protocol):
    event_emitter: Any
    ux_plan: dict[str, Any]
    response_text: str
    correlation_id: str | None
    turn_id: str | None
    response_plan: Any | None
    now_ms: int
    history_stored: bool
    memory_updated: bool
    trace_summary: dict[str, Any] | None
    trace_available: bool
    segmented_messages: list[Any]
    terminal_status: str


class ChatPostprocessDeliveryMixin:
    """Deliver persisted chat outcomes to runtime consumers."""

    async def _deliver_chat_response_outcome(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> ChatParseOutcome:
        if prepared.response_plan is not None:
            return await self._deliver_segmented_chat_response(context, result, prepared)
        return await self._deliver_final_chat_response(context, result, prepared)

    async def _deliver_segmented_chat_response(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> ChatParseOutcome:
        await self._deliver_segmented_notifications(context, result, prepared)
        await self._emit_response_completion(context, result, prepared)
        return await self._emit_chat_response_event(context, result, prepared)

    async def _deliver_segmented_notifications(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> None:
        await self._emit_segmented_agent_response_notifications(
            context=context,
            result=result,
            turn_id=prepared.turn_id,
            response_plan=prepared.response_plan,
            messages=prepared.segmented_messages,
            trace_summary=prepared.trace_summary,
            trace_available=prepared.trace_available,
        )

    async def _deliver_final_chat_response(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> ChatParseOutcome:
        host = cast(_DeliveryPostprocessHostProtocol, self)
        notification_message = await host._get_notification_chat_message(
            turn_id=prepared.turn_id,
            ux_plan=prepared.ux_plan,
        )
        delivery_plan = build_final_response_delivery_plan(
            response_text=prepared.response_text,
            ux_plan=prepared.ux_plan,
            notification_message=notification_message,
            fallback_persona_id=context.active_persona_id,
            resolve_reaction_text=host._resolve_reaction_notification_text,
        )
        if getattr(result, "streamed", False) and delivery_plan.final_message is not None:
            await host._runtime_notifier.emit_chat_message_upsert(
                user_id=context.user_id,
                session_id=context.session_id,
                message_id=delivery_plan.final_message.message_id,
            )

        if not getattr(result, "streamed", False):
            await self._deliver_non_streamed_final_response(
                context=context,
                result=result,
                prepared=prepared,
                delivery_plan=delivery_plan,
            )
        else:
            await self._deliver_streamed_external_response(
                context=context,
                result=result,
                prepared=prepared,
                delivery_plan=delivery_plan,
            )
            await self._emit_response_completion(context, result, prepared)

        return await self._emit_chat_response_event(context, result, prepared)

    async def _deliver_non_streamed_final_response(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
        delivery_plan: Any,
    ) -> None:
        await self._deliver_agent_response(
            context=context,
            turn_id=prepared.turn_id,
            response_text=delivery_plan.response_text,
            attachments=list(getattr(result, "attachments", []) or []),
            message_payload=dict(getattr(result, "message_payload", {}) or {}),
            trace_summary=prepared.trace_summary,
            trace_available=prepared.trace_available,
            ux_plan=result.ux_plan,
            message_id=delivery_plan.message_id,
            message_kind=delivery_plan.message_kind,
            persona_id=delivery_plan.persona_id,
        )

    async def _emit_response_completion(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> None:
        host = cast(_DeliveryPostprocessHostProtocol, self)
        await host.emit_execution_control_notification(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=prepared.turn_id,
            run_id=context.session_run_id,
            state=prepared.terminal_status,
            can_cancel=False,
        )

    async def _deliver_streamed_external_response(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
        delivery_plan: Any,
    ) -> None:
        """Deliver the assembled response only to non-SSE channels.

        The desktop SSE surface already consumed the stream chunks. External
        channels that do not support streaming still need one final response,
        and it must be sent only after the local chat outcome is durable.
        """

        await self._deliver_agent_response(
            context=context,
            turn_id=prepared.turn_id,
            response_text=delivery_plan.response_text,
            attachments=list(getattr(result, "attachments", []) or []),
            message_payload=dict(getattr(result, "message_payload", {}) or {}),
            trace_summary=prepared.trace_summary,
            trace_available=prepared.trace_available,
            ux_plan=result.ux_plan,
            message_id=delivery_plan.message_id,
            message_kind=delivery_plan.message_kind,
            persona_id=delivery_plan.persona_id,
            exclude_chat_sse=True,
        )

    async def _emit_chat_response_event(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> ChatParseOutcome:
        await prepared.event_emitter.emit_chat_response_event(
            user_id=context.user_id,
            session_id=context.session_id,
            response=prepared.response_text,
            correlation_id=prepared.correlation_id,
            turn_id=prepared.turn_id,
            trace_summary=prepared.trace_summary,
            trace_available=prepared.trace_available,
        )
        return ChatParseOutcome(True, prepared.history_stored, prepared.memory_updated, False)

    async def _hide_persisted_rhythm_segments(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
    ) -> bool:
        host = cast(_DeliveryPostprocessHostProtocol, self)
        normalized_turn_id = str(turn_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if host._chat_store is None or not normalized_turn_id or not normalized_session_id:
            return False
        try:
            messages = await host._chat_store.list_messages(session_id=normalized_session_id)
            for message in messages:
                if (
                    message.turn_id == normalized_turn_id
                    and message.message_kind == "assistant_rhythm_segment"
                    and message.is_visible
                ):
                    await host._chat_store.hide_message(
                        session_id=normalized_session_id,
                        message_id=message.message_id,
                    )
            return True
        except Exception as exc:
            logger.warning("Failed to hide persisted rhythm segments: %s", exc)
            return False

    async def _deliver_agent_response(
        self,
        *,
        context: ChatRuntimeContext,
        turn_id: str | None,
        response_text: str,
        attachments: list[dict[str, Any]] | None,
        message_payload: dict[str, Any] | None,
        trace_summary: dict[str, Any] | None,
        trace_available: bool,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
        persona_id: str | None,
        exclude_chat_sse: bool = False,
        exclude_channel_types: frozenset[str] = frozenset(),
    ) -> DeliveryFanoutResult:
        host = cast(_DeliveryPostprocessHostProtocol, self)
        if host._deliver_final_response is None:
            return DeliveryFanoutResult()
        content = DeliveryContent(
            text=response_text,
            attachments=tuple(attachments or ()),
            turn_id=turn_id,
            message_id=message_id,
            message_kind=message_kind,
            persona_id=str(persona_id or "").strip() or None,
            trace_summary=trace_summary,
            trace_available=trace_available,
            ux_plan=ux_plan,
            message_payload=dict(message_payload or {}),
        )
        delivery_kwargs: dict[str, Any] = {"content": content}
        if exclude_chat_sse:
            delivery_kwargs["exclude_chat_sse"] = True
        if exclude_channel_types:
            delivery_kwargs["exclude_channel_types"] = tuple(
                sorted(exclude_channel_types)
            )
        return await host._deliver_final_response(context, **delivery_kwargs)

    async def _emit_segmented_agent_response_notifications(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        turn_id: str | None,
        response_plan: Any,
        messages: Any,
        trace_summary: dict[str, Any] | None,
        trace_available: bool,
    ) -> None:
        attachments = list(getattr(result, "attachments", []) or [])
        total = len(messages)
        excluded_channel_types: set[str] = set()
        for index, message in enumerate(messages):
            try:
                if index > 0:
                    delay_ms = 0
                    if index < len(response_plan.segments):
                        delay_ms = int(response_plan.segments[index].delay_ms or 0)
                    if delay_ms > 0:
                        await asyncio.sleep(delay_ms / 1000.0)
                segment_payload = self._parse_message_payload(message.payload_json)
                delivery_result = await self._deliver_agent_response(
                    context=context,
                    turn_id=turn_id,
                    response_text=str(message.content_text or ""),
                    attachments=attachments if index == total - 1 else [],
                    message_payload=segment_payload,
                    trace_summary=trace_summary,
                    trace_available=trace_available,
                    ux_plan=result.ux_plan,
                    message_id=message.message_id,
                    message_kind=message.message_kind,
                    persona_id=message.persona_id,
                    exclude_channel_types=frozenset(excluded_channel_types),
                )
                failures = delivery_result.failures
                if not failures:
                    continue
                failed_types = {
                    str(failure.target.channel_type or "").strip()
                    for failure in failures
                }
                failed_types.discard("")
                excluded_channel_types.update(failed_types)
                logger.warning(
                    "Segmented response notification failed for channel targets; "
                    "later segments will skip those channels",
                    turn_id=turn_id,
                    segment_index=index,
                    failed_channel_types=sorted(failed_types),
                    successful_channels=len(delivery_result.receipts),
                )
            except Exception:
                logger.warning(
                    "Segmented response notification stopped after an unknown "
                    "delivery failure; keeping the durable segmented response",
                    turn_id=turn_id,
                    segment_index=index,
                    exc_info=True,
                )
                return

    @staticmethod
    def _parse_message_payload(raw_payload_json: str | None) -> dict[str, Any]:
        if not raw_payload_json:
            return {}
        try:
            parsed = json.loads(raw_payload_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


__all__ = ["ChatPostprocessDeliveryMixin"]
