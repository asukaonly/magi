"""Final response delivery helpers for chat post-processing."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Protocol, cast

from magi_plugin_sdk.delivery import DeliveryContent

from magi.agent.task_agents.common import ExecutionResult
from magi.agent.task_agents.handlers.contracts import ChatParseOutcome, ChatRuntimeContext
from magi.core.logger import get_logger

from .final_response_plan import build_final_response_delivery_plan

logger = get_logger(__name__)


class _DeliveryPostprocessHostProtocol(Protocol):
    _chat_store: Any
    _deliver_final_response: Callable[..., Awaitable[list]] | None
    _runtime_notifier: Any


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
        await self._project_segmented_chat_response(context, prepared)
        try:
            await self._deliver_segmented_notifications(context, result, prepared)
        except Exception as exc:
            logger.warning(
                "Segmented chat response notification failed; falling back to final message: %s",
                exc,
            )
            await self._fallback_segmented_response_to_final(context, result, prepared)
            return await self._emit_chat_response_event(context, result, prepared)
        return await self._emit_chat_response_event(context, result, prepared)

    async def _project_segmented_chat_response(
        self,
        context: ChatRuntimeContext,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> None:
        await self._project_canonical_assistant_response(
            context=context,
            turn_id=prepared.turn_id,
            message_id=(
                prepared.segmented_messages[0].message_id if prepared.segmented_messages else None
            ),
            response_text=prepared.response_text,
            created_at_ms=prepared.now_ms,
        )

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

    async def _fallback_segmented_response_to_final(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> None:
        await self._hide_persisted_rhythm_segments(
            session_id=context.session_id,
            turn_id=prepared.turn_id,
        )
        await self._persist_final_response_outcome(context, result, prepared)
        notification_message = await self._get_notification_chat_message(
            turn_id=prepared.turn_id,
            ux_plan=prepared.ux_plan,
        )
        await self._project_final_chat_message(
            context=context,
            final_message=(
                notification_message
                if notification_message and notification_message.message_kind == "assistant_final"
                else None
            ),
        )
        await self._deliver_agent_response(
            context=context,
            turn_id=prepared.turn_id,
            response_text=prepared.response_text,
            attachments=list(getattr(result, "attachments", []) or []),
            message_payload=dict(getattr(result, "message_payload", {}) or {}),
            orchestration_id=result.orchestration_id,
            trace_summary=prepared.trace_summary,
            trace_available=prepared.trace_available,
            ux_plan=result.ux_plan,
            message_id=notification_message.message_id if notification_message is not None else None,
            message_kind=(
                notification_message.message_kind if notification_message is not None else "assistant_final"
            ),
            persona_id=(
                notification_message.persona_id
                if notification_message is not None
                else context.active_persona_id
            ),
        )

    async def _deliver_final_chat_response(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> ChatParseOutcome:
        notification_message = await self._get_notification_chat_message(
            turn_id=prepared.turn_id,
            ux_plan=prepared.ux_plan,
        )
        delivery_plan = build_final_response_delivery_plan(
            response_text=prepared.response_text,
            ux_plan=prepared.ux_plan,
            notification_message=notification_message,
            fallback_persona_id=context.active_persona_id,
            resolve_reaction_text=self._resolve_reaction_notification_text,
        )
        await self._project_final_chat_message(
            context=context,
            final_message=delivery_plan.final_message,
        )
        host = cast(_DeliveryPostprocessHostProtocol, self)
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
            await self._emit_stream_completion(context, result, prepared)

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
            orchestration_id=result.orchestration_id,
            trace_summary=prepared.trace_summary,
            trace_available=prepared.trace_available,
            ux_plan=result.ux_plan,
            message_id=delivery_plan.message_id,
            message_kind=delivery_plan.message_kind,
            persona_id=delivery_plan.persona_id,
        )

    async def _emit_stream_completion(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedDeliveryStateProtocol,
    ) -> None:
        await self.emit_execution_control_notification(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=prepared.turn_id,
            run_id=context.session_run_id,
            orchestration_id=result.orchestration_id,
            state="completed",
            can_cancel=False,
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
            orchestration_id=result.orchestration_id,
            trace_summary=prepared.trace_summary,
            trace_available=prepared.trace_available,
        )
        return ChatParseOutcome(True, prepared.history_stored, prepared.memory_updated, False)

    async def _hide_persisted_rhythm_segments(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
    ) -> None:
        host = cast(_DeliveryPostprocessHostProtocol, self)
        normalized_turn_id = str(turn_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if host._chat_store is None or not normalized_turn_id or not normalized_session_id:
            return
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
        except Exception as exc:
            logger.warning("Failed to hide persisted rhythm segments: %s", exc)

    async def _deliver_agent_response(
        self,
        *,
        context: ChatRuntimeContext,
        turn_id: str | None,
        response_text: str,
        attachments: list[dict[str, Any]] | None,
        message_payload: dict[str, Any] | None,
        orchestration_id: str | None,
        trace_summary: dict[str, Any] | None,
        trace_available: bool,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
        persona_id: str | None,
    ) -> None:
        host = cast(_DeliveryPostprocessHostProtocol, self)
        if host._deliver_final_response is None:
            return
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
            orchestration_id=orchestration_id,
        )
        await host._deliver_final_response(context, content=content)

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
        for index, message in enumerate(messages):
            if index > 0:
                delay_ms = 0
                if index < len(response_plan.segments):
                    delay_ms = int(response_plan.segments[index].delay_ms or 0)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)
            segment_payload = self._parse_message_payload(message.payload_json)
            await self._deliver_agent_response(
                context=context,
                turn_id=turn_id,
                response_text=str(message.content_text or ""),
                attachments=attachments if index == total - 1 else [],
                message_payload=segment_payload,
                orchestration_id=result.orchestration_id,
                trace_summary=trace_summary,
                trace_available=trace_available,
                ux_plan=result.ux_plan,
                message_id=message.message_id,
                message_kind=message.message_kind,
                persona_id=message.persona_id,
            )

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
