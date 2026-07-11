"""Direct LLM execution handler for chat task-agent turns."""

from __future__ import annotations

from typing import Any

from ....agent.message_utils import append_latest_user_message
from ....context.window_budget import build_context_window_budget, estimate_context_tokens
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
    RhythmPersonaSignal,
)
from .handler_helpers import (
    resolve_turn_workspace_path as _resolve_turn_workspace_path,
    serialize_ux_plan as _serialize_ux_plan,
)
from .attachment_context import resolve_effective_turn_attachments
from ...run.ports import AttachmentResolverPort, NullAttachmentResolver
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


def _extract_persona_rhythm(prompt_context: Any) -> "RhythmPersonaSignal | None":
    """Pull the rhythm-relevant persona signals off the already-built turn plan.

    Tolerant by design: any missing link in the chain yields None so the chat
    path never breaks when there is no active persona / plan.
    """
    self_memory = getattr(prompt_context, "self_memory", None)
    plan = getattr(self_memory, "persona_turn_plan", None)
    if plan is None:
        return None
    idiolect = getattr(plan, "idiolect", None)
    sentence_style = ""
    chattiness = 0.5
    if isinstance(idiolect, dict):
        sentence_style = str(idiolect.get("sentence_style", "") or "")
        raw_chattiness = idiolect.get("chattiness", 0.5)
        if raw_chattiness is not None:
            try:
                chattiness = max(0.0, min(1.0, float(raw_chattiness)))
            except (TypeError, ValueError):
                chattiness = 0.5
    raw_intensity = getattr(plan, "persona_intensity", 1)
    return RhythmPersonaSignal(
        register=str(getattr(plan, "register", "casual") or "casual"),
        persona_intensity=int(raw_intensity) if raw_intensity is not None else 1,
        sentence_style=sentence_style,
        chattiness=chattiness,
    )


class DirectLLMHandler(BaseExecutionHandler):
    mode = ExecutionMode.DIRECT_LLM

    @property
    def _attachment_resolver(self) -> AttachmentResolverPort:
        # Duck-typed deps (e.g. test SimpleNamespace) may omit the field;
        # fall back to a null resolver so attachment resolution is a no-op
        # rather than touching chat.
        resolver = getattr(self._deps, "attachment_resolver", None)
        return resolver if resolver is not None else NullAttachmentResolver()

    async def build_request(self, request: ExecutionRequest) -> DirectLLMRequest:
        attachments = resolve_effective_turn_attachments(
            request.context, resolver=self._attachment_resolver
        )
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
        effective_system_prompt = self._deps.prompt_service.augment_system_prompt_with_reply_context(
            system_prompt=prompt_package.system_prompt,
            reply_context=getattr(request.context, "reply_context", None),
            recent_tool_state=getattr(request.context, "recent_tool_state", None),
        )
        context_budget = build_context_window_budget(self._deps.model_context_provider())
        history_budget = max(
            1,
            context_budget.compaction_trigger_tokens
            - estimate_context_tokens(effective_system_prompt),
        )
        return DirectLLMRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=effective_system_prompt,
            messages=append_latest_user_message(
                request.context.history,
                turn,
                resolver=self._attachment_resolver,
                history_token_budget=history_budget,
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
        turn_id = getattr(request.context.latest_payload, "turn_id", None)
        event_context = _build_llm_event_context(request.context, turn_id)
        unsupported = self._build_unsupported_image_result_if_needed(
            request=request,
            turn_id=turn_id,
            llm_trace=llm_trace,
        )
        if unsupported is not None:
            return unsupported

        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)
        if streaming_enabled:
            return await self._execute_streaming(
                request=request,
                control=control,
                event_context=event_context,
                turn_id=turn_id,
                llm_trace=llm_trace,
            )
        return await self._execute_non_streaming(
            request=request,
            control=control,
            event_context=event_context,
            turn_id=turn_id,
            llm_trace=llm_trace,
        )

    def _build_unsupported_image_result_if_needed(
        self,
        *,
        request: DirectLLMRequest,
        turn_id: object,
        llm_trace: dict[str, object],
    ) -> ExecutionResult | None:
        attachments = resolve_effective_turn_attachments(
            request.context, resolver=self._attachment_resolver
        )
        if _image_attachments_supported(request.context, attachments):
            return None
        return ExecutionResult(
            mode=request.mode,
            response_text=_image_vision_unsupported_response(),
            root_user_message=request.context.latest_user_message,
            turn_id=turn_id,
            llm_trace=llm_trace,
            ux_plan=_serialize_ux_plan(request.intent),
        )

    async def _execute_streaming(
        self,
        *,
        request: DirectLLMRequest,
        control: Any,
        event_context: dict[str, object],
        turn_id: object,
        llm_trace: dict[str, object],
    ) -> ExecutionResult:
        abort_reason: str | None = None
        chunks: list[str] = []
        try:
            chunks, abort_reason = await self._collect_stream_chunks(
                request=request,
                control=control,
                event_context=event_context,
            )
        finally:
            await self._dispatch_final_stream_boundary(request, turn_id)
        response_text = "".join(chunks)
        return self._build_execution_result(
            request=request,
            response_text=response_text,
            turn_id=turn_id,
            llm_trace=_with_abort_reason(llm_trace, abort_reason),
            streamed=bool(response_text),
        )

    async def _collect_stream_chunks(
        self,
        *,
        request: DirectLLMRequest,
        control: Any,
        event_context: dict[str, object],
    ) -> tuple[list[str], str | None]:
        chunks: list[str] = []
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
        except CancellationRaised as exc:
            return chunks, f"cancel:{exc.reason or 'unknown'}"
        except RetractRaised as exc:
            return chunks, _retract_abort_reason(exc)
        return chunks, None

    async def _dispatch_final_stream_boundary(
        self,
        request: DirectLLMRequest,
        turn_id: object,
    ) -> None:
        # Always emit one final boundary chunk so channels can close/flush.
        coordinator = getattr(self._deps, "coordinator", None)
        if coordinator is None:
            return
        try:
            await coordinator.dispatch_stream_chunk(
                session_id=request.context.session_id,
                user_id=request.context.user_id,
                turn_id=str(turn_id or "") or None,
                text="",
                is_final=True,
                seq=0,
            )
        except Exception:
            pass

    async def _execute_non_streaming(
        self,
        *,
        request: DirectLLMRequest,
        control: Any,
        event_context: dict[str, object],
        turn_id: object,
        llm_trace: dict[str, object],
    ) -> ExecutionResult:
        try:
            response_text = await self._deps.prompt_service.call_llm(
                system_prompt=request.system_prompt,
                messages=request.messages,
                thinking_depth=request.thinking_depth,
                llm_trace_callback=_llm_trace_updater(llm_trace),
                event_context=event_context,
                control=control,
            )
        except CancellationRaised as exc:
            return self._build_execution_result(
                request=request,
                response_text="",
                turn_id=turn_id,
                llm_trace={**llm_trace, "abort_reason": f"cancel:{exc.reason or 'unknown'}"},
            )
        except RetractRaised as exc:
            return self._build_execution_result(
                request=request,
                response_text="",
                turn_id=turn_id,
                llm_trace={**llm_trace, "abort_reason": _retract_abort_reason(exc)},
            )
        return self._build_execution_result(
            request=request,
            response_text=response_text,
            turn_id=turn_id,
            llm_trace=dict(llm_trace),
            persona_rhythm=_extract_persona_rhythm(request.prompt_context),
        )

    @staticmethod
    def _build_execution_result(
        *,
        request: DirectLLMRequest,
        response_text: str,
        turn_id: object,
        llm_trace: dict[str, object],
        streamed: bool = False,
        persona_rhythm: RhythmPersonaSignal | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            mode=request.mode,
            response_text=response_text,
            root_user_message=request.context.latest_user_message,
            turn_id=turn_id,
            llm_trace=llm_trace,
            ux_plan=_serialize_ux_plan(request.intent),
            streamed=streamed,
            persona_rhythm=persona_rhythm,
        )


def _llm_trace_updater(llm_trace: dict[str, object]):
    async def _capture_llm_trace(payload: dict[str, object]) -> None:
        llm_trace.update(payload)

    return _capture_llm_trace


def _retract_abort_reason(exc: RetractRaised) -> str:
    reason = (exc.payload.reason if exc.payload else None) or "unknown"
    return f"retract:{reason}"


def _with_abort_reason(
    llm_trace: dict[str, object],
    abort_reason: str | None,
) -> dict[str, object]:
    llm_trace_out = dict(llm_trace)
    if abort_reason:
        llm_trace_out["abort_reason"] = abort_reason
    return llm_trace_out


__all__ = ["DirectLLMHandler"]
