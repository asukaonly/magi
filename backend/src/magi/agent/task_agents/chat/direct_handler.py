"""Direct LLM execution handler for chat task-agent turns."""

from __future__ import annotations

from ....agent.message_utils import append_latest_user_message
from ....context.scenarios import Scenario
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


class DirectLLMHandler(BaseExecutionHandler):
    mode = ExecutionMode.DIRECT_LLM

    async def build_request(self, request: ExecutionRequest) -> DirectLLMRequest:
        prompt_package = await self._deps.context_service.build_prompt_package(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            attachments=list(getattr(request.context.latest_payload, "attachments", []) or []),
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
            workspace_path=_resolve_turn_workspace_path(request.context),
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
                request.context.latest_user_message,
                history_limit=10,
                attachments=list(getattr(request.context.latest_payload, "attachments", []) or []),
                user_id=request.context.user_id,
                session_id=request.context.session_id,
            ),
            thinking_depth=request.intent.thinking_depth,
        )

    async def execute(self, request: DirectLLMRequest) -> ExecutionResult:
        llm_trace: dict[str, object] = {}
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)

        async def _capture_llm_trace(payload: dict[str, object]) -> None:
            llm_trace.update(payload)

        turn_id = getattr(request.context.latest_payload, "turn_id", None)

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