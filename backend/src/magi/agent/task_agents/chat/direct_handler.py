"""Direct LLM execution handler for chat task-agent turns."""

from __future__ import annotations

from ....agent.message_utils import append_latest_user_message
from ....agent.turn_input import UserTurnInput
from ....context.scenarios import Scenario
from .... import i18n as core_i18n
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


class DirectLLMHandler(BaseExecutionHandler):
    mode = ExecutionMode.DIRECT_LLM

    async def build_request(self, request: ExecutionRequest) -> DirectLLMRequest:
        attachments = list(getattr(request.context.latest_payload, "attachments", []) or [])
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
            ),
            thinking_depth=request.intent.thinking_depth,
        )

    async def execute(self, request: DirectLLMRequest) -> ExecutionResult:
        llm_trace: dict[str, object] = {}
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)

        async def _capture_llm_trace(payload: dict[str, object]) -> None:
            llm_trace.update(payload)

        turn_id = getattr(request.context.latest_payload, "turn_id", None)
        attachments = list(getattr(request.context.latest_payload, "attachments", []) or [])
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
            async for event in self._deps.prompt_service.call_llm_stream(
                system_prompt=request.system_prompt,
                messages=request.messages,
                thinking_depth=request.thinking_depth,
            ):
                if event.kind == "text_delta" and event.text:
                    chunks.append(event.text)
            response_text = "".join(chunks)
            return ExecutionResult(
                mode=request.mode,
                response_text=response_text,
                root_user_message=request.context.latest_user_message,
                turn_id=turn_id,
                llm_trace=dict(llm_trace),
                ux_plan=_serialize_ux_plan(request.intent),
                streamed=bool(response_text),
            )

        response_text = await self._deps.prompt_service.call_llm(
            system_prompt=request.system_prompt,
            messages=request.messages,
            thinking_depth=request.thinking_depth,
            llm_trace_callback=_capture_llm_trace,
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
