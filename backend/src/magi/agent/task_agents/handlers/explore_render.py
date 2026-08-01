"""Explore task routing and render handlers for chat task agents."""

from __future__ import annotations

import time
from typing import Any, Optional

from ....config.models import ThinkingDepth
from ....core.logger import get_logger
from ....agent.runtime.contracts import FactRecord
from ....agent.runtime.types import TaskAgentType
from ....context.scenarios import Scenario
from ....utils.diagnostic_logging import full_content_logging_enabled
from ..common import (
    BaseExecutionHandler,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExploreTaskCompletedPayload,
    ExploreTaskRequestPayload,
    ExploreRenderRequest,
)
from ..explore.constants import EXPLORE_TASK_REQUEST
from .handler_helpers import serialize_ux_plan as _serialize_ux_plan

logger = get_logger(__name__)


async def start_explore_task_agent(
    deps: Any,
    request: ExecutionRequest,
) -> Optional[ExecutionResult]:
    route_decision = getattr(request.intent, "route_decision", None)
    if route_decision is None or getattr(route_decision, "profile", None) != "explore":
        return None
    latest_fact = request.context.latest_fact
    history = deps.prompt_service.filter_history_for_aggregation(request.context.history)
    payload = ExploreTaskRequestPayload(
        user_id=request.context.user_id,
        session_id=request.context.session_id,
        content=request.context.latest_user_message,
        run_id=request.context.session_run_id,
        run_revision=request.context.session_run_revision,
        history_snapshot=history,
        upstream_task_agent_type=TaskAgentType.CHAT.value,
        upstream_task_agent_id=request.context.session_id or request.context.user_id,
        turn_id=getattr(request.context.latest_payload, "turn_id", None),
    )
    fact = FactRecord(
        agent_id=f"{TaskAgentType.EXPLORE.value}:{request.context.user_id}",
        event_type=EXPLORE_TASK_REQUEST,
        payload=payload.to_dict(),
        agent_type=TaskAgentType.EXPLORE.value,
        agent_instance_id=request.context.user_id,
        timestamp=time.time(),
        correlation_id=latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
        user_message_generation=(
            request.context.user_message_generation
            if request.context.user_message_generation is not None
            else (
                latest_fact.user_message_generation
                if isinstance(latest_fact, FactRecord)
                else None
            )
        ),
    )
    manager = deps.get_task_agent_manager()
    try:
        enqueued = False if manager is None else await manager.add_fact_to_agent(TaskAgentType.EXPLORE, request.context.user_id, fact)
    except Exception as exc:
        logger.warning(
            "Failed to route request to ExploreTaskAgent | user_id=%s error=%s",
            request.context.user_id,
            exc,
        )
        enqueued = False
    if not enqueued:
        return ExecutionResult(
            mode=request.mode,
            response_text="Failed to start Explore task decomposition for this request.",
            root_user_message=request.context.latest_user_message,
            correlation_id=fact.correlation_id,
            turn_id=payload.turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )
    deps.context_assembler.append_user_message(
        request.context.history_key,
        request.context.latest_user_message,
    )
    return ExecutionResult(
        mode=request.mode,
        skip_emit=True,
        turn_id=payload.turn_id,
        ux_plan=_serialize_ux_plan(request.intent),
    )


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
            persona_routing_hint=getattr(request.intent, "persona_routing_hint", None),
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


__all__ = ["ExploreRenderHandler", "start_explore_task_agent"]
