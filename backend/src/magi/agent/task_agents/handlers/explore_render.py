"""Explore task routing and render handlers for chat task agents."""

from __future__ import annotations

from typing import Any

from ....config.models import ThinkingDepth
from ....core.logger import get_logger
from ....agent.runtime.contracts import FactRecord
from ....context.scenarios import Scenario
from ....i18n import t
from ....utils.diagnostic_logging import full_content_logging_enabled
from ..common import (
    BaseExecutionHandler,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExploreTaskCompletedPayload,
    ExploreRenderRequest,
    IncomingFactKind,
)
from .handler_helpers import serialize_ux_plan as _serialize_ux_plan

logger = get_logger(__name__)


class ExploreRenderHandler(BaseExecutionHandler):
    mode = ExecutionMode.EXPLORE_TASK_RENDER

    async def build_request(self, request: ExecutionRequest) -> ExploreRenderRequest:
        latest_payload = request.context.latest_payload
        return ExploreRenderRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            markdown_dossier=(
                latest_payload.markdown_dossier
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else ""
            ),
            root_user_message=(
                latest_payload.root_user_message
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else request.context.latest_user_message
            ).strip(),
            message_started_at=(
                latest_payload.message_started_at
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else None
            ),
            orchestration_id=(
                latest_payload.orchestration_id
                if isinstance(latest_payload, ExploreTaskCompletedPayload)
                else None
            ),
        )

    async def execute(self, request: ExploreRenderRequest) -> ExecutionResult:
        dossier = request.markdown_dossier
        root_user_message = str(request.root_user_message or request.context.latest_user_message).strip()
        orchestration_id = request.orchestration_id
        if request.context.incoming_fact_kind == IncomingFactKind.EXPLORE_TASK_FAILED:
            return ExecutionResult(
                mode=request.mode,
                response_text=dossier
                or t(
                    "chat.explore.execution_failed_generic",
                    fallback="The exploration stopped before it could produce a result.",
                ),
                root_user_message=root_user_message,
                correlation_id=(
                    request.context.latest_fact.correlation_id
                    if isinstance(request.context.latest_fact, FactRecord)
                    else None
                ),
                orchestration_id=orchestration_id,
                message_started_at=request.message_started_at,
                turn_id=getattr(request.context.latest_payload, "turn_id", None),
                ux_plan=_serialize_ux_plan(request.intent),
            )
        if not dossier:
            return ExecutionResult(
                mode=request.mode,
                response_text=self._deps.prompt_service.build_explore_render_fallback(root_user_message),
                root_user_message=root_user_message,
                correlation_id=request.context.latest_fact.correlation_id if isinstance(request.context.latest_fact, FactRecord) else None,
                orchestration_id=orchestration_id,
                message_started_at=request.message_started_at,
                turn_id=getattr(request.context.latest_payload, "turn_id", None),
                ux_plan=_serialize_ux_plan(request.intent),
            )

        filtered_history = self._deps.prompt_service.filter_history_for_aggregation(request.context.history)
        system_prompt = await self._deps.context_service.build_system_prompt(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=root_user_message,
            task_category="analysis",
            scenario=Scenario.ANALYSIS,
            include_tool_catalog=False,
            persona_id=getattr(request.context, "active_persona_id", None),
        )
        messages = filtered_history + [
            {
                "role": "user",
                "content": self._deps.prompt_service.build_explore_render_message(root_user_message, dossier),
            }
        ]
        try:
            response = await self._deps.prompt_service.call_llm(
                system_prompt=system_prompt,
                messages=messages,
                thinking_depth=ThinkingDepth.NONE,
                event_context={
                    "request_kind": "task_agent:explore_render",
                    "agent_id": "explore_render",
                    "session_id": request.context.session_id,
                    "turn_id": getattr(request.context.latest_payload, "turn_id", None),
                },
            )
        except Exception as exc:
            logger.warning(
                "Explore dossier rendering failed | orchestration_id=%s error=%s",
                orchestration_id,
                exc,
            )
            response = ""
        if not response.strip():
            if full_content_logging_enabled():
                logger.warning(
                    "Explore dossier rendering returned empty response | "
                    "orchestration_id=%s dossier_preview=%s",
                    orchestration_id,
                    dossier[:300],
                )
            else:
                logger.warning(
                    "Explore dossier rendering returned empty response | "
                    "orchestration_id=%s dossier_chars=%d",
                    orchestration_id,
                    len(dossier),
                )
            response = self._deps.prompt_service.build_explore_render_fallback(root_user_message, dossier)
        response = self._deps.prompt_service.format_explore_render_response(response)
        return ExecutionResult(
            mode=request.mode,
            response_text=response.strip(),
            root_user_message=root_user_message,
            correlation_id=request.context.latest_fact.correlation_id if isinstance(request.context.latest_fact, FactRecord) else None,
            orchestration_id=orchestration_id,
            message_started_at=request.message_started_at,
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
            ux_plan=_serialize_ux_plan(request.intent),
        )


__all__ = ["ExploreRenderHandler"]
