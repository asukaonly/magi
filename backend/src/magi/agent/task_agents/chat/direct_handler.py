"""Direct LLM execution handler for chat task-agent turns."""

from __future__ import annotations

from ....agent.message_utils import append_latest_user_message
from ....agent.turn_input import UserTurnInput
from ....context.scenarios import Scenario
from .... import i18n as core_i18n
from ....llm.cancellable_client import CancellationRaised, RetractRaised
from ..common import (
    BaseExecutionHandler,
    DirectLLMRequest,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
)
from .handler_helpers import (
    resolve_turn_workspace_path as _resolve_turn_workspace_path,
    serialize_ux_plan as _serialize_ux_plan,
)
from .attachment_context import resolve_effective_turn_attachments
from ....runtime_trace import enrich_event_context_with_turn_trace

IMAGE_VISION_UNSUPPORTED_RESPONSE_KEY = "chat.image_vision_unsupported"


def _is_image_attachment(attachment: object) -> bool:
    return isinstance(attachment, dict) and str(attachment.get("kind") or "").strip() == "image"


def _has_image_attachment(attachments: list[object]) -> bool:
    return any(_is_image_attachment(attachment) for attachment in attachments)


def _core_model_supports_vision(context: object) -> bool:
    return bool(getattr(context, "core_model_supports_vision", False))


def _image_attachments_supported(context: object, attachments: list[object]) -> bool:
    return not _has_image_attachment(attachments) or _core_model_supports_vision(context)


def _image_vision_unsupported_response() -> str:
    return core_i18n.t(IMAGE_VISION_UNSUPPORTED_RESPONSE_KEY)


def _build_llm_event_context(context: object, turn_id: object) -> dict[str, object]:
    return enrich_event_context_with_turn_trace(
        {
            "request_kind": "task_agent:chat_direct",
            "session_id": getattr(context, "session_id", None),
            "turn_id": turn_id,
        }
    )


class DirectLLMHandler(BaseExecutionHandler):
    mode = ExecutionMode.DIRECT_LLM

    async def build_request(self, request: ExecutionRequest) -> DirectLLMRequest:
        attachments = resolve_effective_turn_attachments(request.context)
        attachments_for_model = (
            attachments
            if _image_attachments_supported(request.context, attachments)
            else [attachment for attachment in attachments if not _is_image_attachment(attachment)]
        )
        turn = UserTurnInput(
            text=request.context.latest_user_message,
            attachments=attachments_for_model,
            user_id=request.context.user_id,
            session_id=request.context.session_id,
        )
        prompt_package = await self._deps.context_service.build_prompt_package(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            attachments=attachments,
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
            workspace_path=_resolve_turn_workspace_path(request.context),
            persona_id=getattr(request.context, "active_persona_id", None),
            persona_routing_hint=getattr(request.intent, "persona_routing_hint", None),
        )
        return DirectLLMRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=self._deps.prompt_service.augment_system_prompt_with_reply_context(
                system_prompt=prompt_package.system_prompt,
                reply_context=getattr(request.context, "reply_context", None),
                recent_tool_state=getattr(request.context, "recent_tool_state", None),
            ),
            messages=append_latest_user_message(
                request.context.history,
                turn,
                session_summary=getattr(request.context, "session_summary", None),
                session_origin=getattr(request.context, "session_origin", None),
                reply_context=getattr(request.context, "reply_context", None),
            ),
            thinking_depth=request.intent.thinking_depth,
        )

    async def execute(self, request: DirectLLMRequest) -> ExecutionResult:
        """Execute a direct LLM call, propagating RunControl cancel/retract signals.

        Reads ``request.context.control`` and passes it to both the streaming
        and non-streaming prompt-service paths.  When the token is already
        cancelled (or retracted) before any chunks are emitted, or mid-stream,
        the handler catches :class:`~magi.llm.cancellable_client.CancellationRaised`
        and :class:`~magi.llm.cancellable_client.RetractRaised` and returns a
        partial :class:`ExecutionResult` with an ``abort_reason`` entry in
        ``llm_trace``.
        """
        control = request.context.control
        llm_trace: dict[str, object] = {}
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)

        async def _capture_llm_trace(payload: dict[str, object]) -> None:
            llm_trace.update(payload)

        turn_id = getattr(request.context.latest_payload, "turn_id", None)
        event_context = _build_llm_event_context(request.context, turn_id)
        attachments = resolve_effective_turn_attachments(request.context)
        if not _image_attachments_supported(request.context, attachments):
            return ExecutionResult(
                mode=request.mode,
                response_text=_image_vision_unsupported_response(),
                root_user_message=request.context.latest_user_message,
                turn_id=turn_id,
                llm_trace=llm_trace,
                ux_plan=_serialize_ux_plan(request.intent),
            )

        if streaming_enabled:
            chunks: list[str] = []
            abort_reason: str | None = None
            # Phase G+1: route each text_delta through
            # coordinator.dispatch_stream_chunk so configured channels
            # (chat SSE, telegram, etc.) receive the stream in parallel.
            # ``seq`` is monotonic across delta + final boundary chunks.
            coordinator = getattr(self._deps, "coordinator", None)
            seq = 0
            try:
                try:
                    async for event in self._deps.prompt_service.call_llm_stream(
                        system_prompt=request.system_prompt,
                        messages=request.messages,
                        thinking_depth=request.thinking_depth,
                        event_context=event_context,
                        control=control,
                    ):
                        if event.kind == "text_delta" and event.text:
                            chunks.append(event.text)
                            if coordinator is not None:
                                try:
                                    await coordinator.dispatch_stream_chunk(
                                        session_id=request.context.session_id,
                                        user_id=request.context.user_id,
                                        text=event.text,
                                        is_final=False,
                                        seq=seq,
                                    )
                                except Exception:
                                    # Streaming dispatch errors must never
                                    # interrupt the LLM loop — they're
                                    # purely an additive delivery path.
                                    pass
                                seq += 1
                except CancellationRaised as exc:
                    abort_reason = f"cancel:{exc.reason or 'unknown'}"
                except RetractRaised as exc:
                    abort_reason = f"retract:{(exc.payload.reason if exc.payload else None) or 'unknown'}"
            finally:
                # Always emit one final boundary chunk so channels can
                # close/flush — including when the stream was cancelled
                # or retracted mid-way.
                if coordinator is not None:
                    try:
                        await coordinator.dispatch_stream_chunk(
                            session_id=request.context.session_id,
                            user_id=request.context.user_id,
                            text="",
                            is_final=True,
                            seq=seq,
                        )
                    except Exception:
                        pass
            response_text = "".join(chunks)
            llm_trace_out = dict(llm_trace)
            if abort_reason:
                llm_trace_out["abort_reason"] = abort_reason
            return ExecutionResult(
                mode=request.mode,
                response_text=response_text,
                root_user_message=request.context.latest_user_message,
                turn_id=turn_id,
                llm_trace=llm_trace_out,
                ux_plan=_serialize_ux_plan(request.intent),
                streamed=bool(response_text),
            )

        # Non-streaming path
        try:
            response_text = await self._deps.prompt_service.call_llm(
                system_prompt=request.system_prompt,
                messages=request.messages,
                thinking_depth=request.thinking_depth,
                llm_trace_callback=_capture_llm_trace,
                event_context=event_context,
                control=control,
            )
        except CancellationRaised as exc:
            return ExecutionResult(
                mode=request.mode,
                response_text="",
                root_user_message=request.context.latest_user_message,
                turn_id=turn_id,
                llm_trace={**llm_trace, "abort_reason": f"cancel:{exc.reason or 'unknown'}"},
                ux_plan=_serialize_ux_plan(request.intent),
            )
        except RetractRaised as exc:
            return ExecutionResult(
                mode=request.mode,
                response_text="",
                root_user_message=request.context.latest_user_message,
                turn_id=turn_id,
                llm_trace={**llm_trace, "abort_reason": f"retract:{(exc.payload.reason if exc.payload else None) or 'unknown'}"},
                ux_plan=_serialize_ux_plan(request.intent),
            )
        return ExecutionResult(
            mode=request.mode,
            response_text=response_text,
            root_user_message=request.context.latest_user_message,
            turn_id=turn_id,
            llm_trace=dict(llm_trace),
            ux_plan=_serialize_ux_plan(request.intent),
        )


__all__ = ["DirectLLMHandler"]
