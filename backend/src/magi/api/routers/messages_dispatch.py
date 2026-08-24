"""Message dispatch routes."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from ...core.logger import get_logger
from ... import i18n as core_i18n
from ...mcp.attachment_resolver import resolve_attachment_resources
from ...personality.active_persona import get_current_personality
from ...personality.bootstrap_service import build_bootstrap_l2_priority_metadata
from ...skills.expander import expand_skill
from ...skills.service_access import get_enabled_skill_names
from ...core.runtime_namespace import DEFAULT_RUNTIME_NAMESPACE
from ...utils.agent_logger import get_agent_logger
from ...utils.diagnostic_logging import full_content_logging_enabled
from ..services import dispatch_user_message, get_runtime_system_status
from .messages_models import MessageResponse, UserMessageRequest

logger = get_logger(__name__)
agent_logger = get_agent_logger("api")

message_dispatch_router = APIRouter()

RUNTIME_NOT_READY = "RUNTIME_NOT_READY"


async def _ensure_runtime_ready_for_user_message() -> MessageResponse | None:
    """Return a rejection payload when the runtime cannot consume queued messages yet."""
    runtime_status = await get_runtime_system_status(None)
    if runtime_status.get("runtime_ready"):
        return None

    startup_state = str(
        runtime_status.get("startup_state") or runtime_status.get("runtime_status") or "offline"
    )
    deferred_reason = runtime_status.get("deferred_reason")
    if startup_state == "deferred" and deferred_reason == "llm_selection_pending":
        message = core_i18n.t(
            "chat.runtime.not_ready.llm_selection_pending",
            fallback="AI runtime is not ready yet. Please complete the core model configuration first.",
        )
    elif startup_state == "deferred" and deferred_reason == "llm_configuration_invalid":
        message = core_i18n.t(
            "chat.runtime.not_ready.configuration_invalid",
            fallback="AI runtime configuration is invalid. Please check the enabled provider and model selection.",
        )
    elif startup_state == "starting":
        message = core_i18n.t(
            "chat.runtime.not_ready.starting",
            fallback="AI runtime is still starting. Please retry in a moment.",
        )
    else:
        message = core_i18n.t(
            "chat.runtime.not_ready.startup_pending",
            fallback="AI runtime is not ready yet. Please wait for startup to finish and try again.",
        )

    return MessageResponse(
        success=False,
        message=message,
        data={
            "error": message,
            "error_code": RUNTIME_NOT_READY,
            "runtime_status": runtime_status.get("runtime_status"),
            "startup_state": startup_state,
            "deferred_reason": deferred_reason,
        },
    )


@message_dispatch_router.post("/send", response_model=MessageResponse)
async def send_user_message(request: UserMessageRequest):
    try:
        runtime_not_ready_response = await _ensure_runtime_ready_for_user_message()
        if runtime_not_ready_response is not None:
            _log_runtime_not_ready(request, runtime_not_ready_response)
            return runtime_not_ready_response

        outcome = await _dispatch_api_user_message(request)
        if not outcome.success:
            return _dispatch_rejected_response(request, outcome)

        if outcome.handled_as == "ask_response":
            return _ask_response_recorded_response(request, outcome)

        _log_queued_message(request, outcome)
        return _queued_message_response(request, outcome)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to queue message: {e}")
        agent_logger.error(f"Queue failed | User: {request.user_id} | error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def _log_runtime_not_ready(
    request: UserMessageRequest,
    response: MessageResponse,
) -> None:
    agent_logger.warning(
        "Message dispatch rejected before queueing | User: %s | code: %s | startup_state: %s",
        request.user_id,
        RUNTIME_NOT_READY,
        response.data.get("startup_state") if response.data else None,
    )


async def _dispatch_api_user_message(request: UserMessageRequest):
    metadata, reply_to_message_id = await _prepare_api_dispatch_metadata(request)
    skill_context = metadata.get("skill_invocation")
    message = (
        str(skill_context.get("invocation_text") or "")
        if isinstance(skill_context, dict)
        else request.message
    )
    return await dispatch_user_message(
        source="api",
        user_id=request.user_id,
        message=message,
        session_id=request.session_id,
        attachments=await resolve_attachment_resources(list(request.attachments or [])),
        reply_to_message_id=reply_to_message_id,
        workspace_path=request.workspace_path,
        client_turn_id=request.client_turn_id,
        metadata=metadata,
        runtime_namespace=str(metadata.get("runtime_namespace") or DEFAULT_RUNTIME_NAMESPACE),
        interaction_kind=request.interaction_kind,
        first_context=(
            request.first_context.model_dump(mode="json")
            if request.first_context is not None
            else None
        ),
    )


async def _prepare_api_dispatch_metadata(
    request: UserMessageRequest,
) -> tuple[dict[str, object], str | None]:
    metadata = dict(request.metadata or {})
    metadata.pop("recall_feedback", None)
    metadata.pop("interaction_kind", None)
    metadata.pop("first_context", None)
    metadata.pop("reasoning_preference", None)
    metadata.pop("skill_invocation", None)
    if request.recall_feedback is not None:
        metadata["recall_feedback"] = request.recall_feedback.model_dump(mode="json")
    if request.reasoning_preference is not None:
        metadata["reasoning_preference"] = request.reasoning_preference
    if request.skill_invocation is not None:
        metadata["skill_invocation"] = _build_inline_skill_context(request)
    metadata.update(
        await build_bootstrap_l2_priority_metadata(
            user_id=request.user_id,
            session_id=request.session_id,
            persona_name=get_current_personality(),
            force=request.interaction_kind == "first_context_story",
        )
    )
    reply_to_message_id = str(request.reply_to_message_id or "").strip() or None
    if reply_to_message_id is not None:
        metadata["reply_to_message_id"] = reply_to_message_id
    return metadata, reply_to_message_id


def _build_inline_skill_context(request: UserMessageRequest) -> dict[str, object]:
    invocation = request.skill_invocation
    if invocation is None:
        raise ValueError("skill invocation is required")
    try:
        expansion = expand_skill(
            skill_name=invocation.name,
            arguments=invocation.arguments,
            user_id=request.user_id,
            session_id=str(request.session_id or ""),
            workspace=request.workspace_path,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if expansion is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill {invocation.name!r} not found",
        )
    if invocation.name not in set(get_enabled_skill_names()):
        raise HTTPException(
            status_code=403,
            detail=f"Skill {invocation.name!r} is disabled",
        )
    if not expansion.user_invocable:
        raise HTTPException(
            status_code=403,
            detail=f"Skill {invocation.name!r} is not user-invocable",
        )
    if expansion.context_mode == "fork":
        raise HTTPException(
            status_code=409,
            detail=f"Skill {invocation.name!r} requires a child run",
        )
    return {
        "name": expansion.name,
        "arguments": list(invocation.arguments),
        "invocation_text": expansion.invocation_text,
        "rendered_prompt": expansion.rendered_prompt,
        "content_hash": expansion.content_hash,
        "context_mode": "inline",
        "allowed_tools": list(expansion.allowed_tools or []),
    }


def _dispatch_rejected_response(
    request: UserMessageRequest,
    outcome,
) -> MessageResponse:
    agent_logger.warning(
        f"Message dispatch rejected | User: {request.user_id} | code: {outcome.error_code}"
    )
    return MessageResponse(
        success=False,
        message=outcome.error_message
        or core_i18n.t("chat.dispatch.failed_to_queue", fallback="Failed to queue message"),
        data={
            "user_id": request.user_id,
            "session_id": outcome.session_id,
            "turn_id": outcome.turn_id,
            "message_id": outcome.message_id,
            "error": outcome.error_message,
            "error_code": outcome.error_code,
        },
    )


def _ask_response_recorded_response(
    request: UserMessageRequest,
    outcome,
) -> MessageResponse:
    return MessageResponse(
        success=True,
        message=core_i18n.t("chat.dispatch.ask_response_recorded", fallback="Answer recorded"),
        data={
            "user_id": request.user_id,
            "session_id": outcome.session_id,
            "handled_as": outcome.handled_as,
            "ask_request_id": outcome.ask_request_id,
            "message_length": len(request.message),
            "timestamp": time.time(),
        },
    )


def _log_queued_message(request: UserMessageRequest, outcome) -> None:
    logger.info(
        "Message from %s queued for runtime processing | Queue size: %s",
        request.user_id,
        outcome.queue_size if outcome.queue_size is not None else "unknown",
    )
    if full_content_logging_enabled():
        agent_logger.info(
            "Message received | User: %s | Content: '%s%s' | Length: %s",
            request.user_id,
            request.message[:50],
            "..." if len(request.message) > 50 else "",
            len(request.message),
        )
    else:
        agent_logger.info(
            "Message received | User: %s | Length: %s",
            request.user_id,
            len(request.message),
        )


def _queued_message_response(request: UserMessageRequest, outcome) -> MessageResponse:
    return MessageResponse(
        success=True,
        message=core_i18n.t("chat.dispatch.queued", fallback="Message queued for processing"),
        data={
            "user_id": request.user_id,
            "session_id": outcome.session_id,
            "turn_id": outcome.turn_id,
            "message_id": outcome.message_id,
            "message_length": len(request.message),
            "attachment_count": len(request.attachments or []),
            "timestamp": time.time(),
        },
    )


__all__ = [
    "RUNTIME_NOT_READY",
    "message_dispatch_router",
    "send_user_message",
    "_ensure_runtime_ready_for_user_message",
]
