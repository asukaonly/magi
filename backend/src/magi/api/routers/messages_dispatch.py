"""Message dispatch routes."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from ...core.logger import get_logger
from ... import i18n as core_i18n
from ...mcp.attachment_resolver import resolve_attachment_resources
from ...runtime_defaults import DEFAULT_RUNTIME_NAMESPACE
from ...utils.agent_logger import get_agent_logger
from .messages_common import legacy_messages_module
from .messages_models import MessageResponse, UserMessageRequest

logger = get_logger(__name__)
agent_logger = get_agent_logger("api")

message_dispatch_router = APIRouter()

RUNTIME_NOT_READY = "RUNTIME_NOT_READY"


async def _ensure_runtime_ready_for_user_message() -> MessageResponse | None:
    """Return a rejection payload when the runtime cannot consume queued messages yet."""
    legacy = legacy_messages_module()
    runtime_status = await legacy.get_runtime_system_status(None)
    if runtime_status.get("runtime_ready"):
        return None

    startup_state = str(runtime_status.get("startup_state") or runtime_status.get("runtime_status") or "offline")
    deferred_reason = runtime_status.get("deferred_reason")
    if startup_state == "deferred" and deferred_reason == "llm_selection_pending":
        message = core_i18n.t(
            "chat.runtime.not_ready.llm_selection_pending",
            fallback="AI runtime is not ready yet. Please complete the core or context_decider model configuration first.",
        )
    elif startup_state == "deferred" and deferred_reason == "llm_configuration_invalid":
        message = core_i18n.t(
            "chat.runtime.not_ready.configuration_invalid",
            fallback="AI runtime configuration is invalid. Please check the enabled provider and model selection.",
        )
    elif startup_state == "starting":
        message = core_i18n.t("chat.runtime.not_ready.starting", fallback="AI runtime is still starting. Please retry in a moment.")
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
    legacy = legacy_messages_module()
    try:
        runtime_not_ready_response = await _ensure_runtime_ready_for_user_message()
        if runtime_not_ready_response is not None:
            agent_logger.warning(
                "Message dispatch rejected before queueing | User: %s | code: %s | startup_state: %s",
                request.user_id,
                RUNTIME_NOT_READY,
                runtime_not_ready_response.data.get("startup_state") if runtime_not_ready_response.data else None,
            )
            return runtime_not_ready_response

        normalized_metadata = dict(request.metadata or {})
        normalized_metadata.update(
            await legacy.build_bootstrap_l2_priority_metadata(
                user_id=request.user_id,
                session_id=request.session_id,
                persona_name=legacy.get_current_personality(),
            )
        )
        normalized_reply_to_message_id = str(request.reply_to_message_id or "").strip() or None
        if normalized_reply_to_message_id is not None:
            normalized_metadata["reply_to_message_id"] = normalized_reply_to_message_id

        outcome = await legacy.dispatch_user_message(
            source="api",
            user_id=request.user_id,
            message=request.message,
            session_id=request.session_id,
            attachments=await resolve_attachment_resources(
                list(request.attachments or [])
            ),
            reply_to_message_id=normalized_reply_to_message_id,
            workspace_path=request.workspace_path,
            client_turn_id=request.client_turn_id,
            metadata=normalized_metadata,
            runtime_namespace=str(normalized_metadata.get("runtime_namespace") or DEFAULT_RUNTIME_NAMESPACE),
        )
        if not outcome.success:
            agent_logger.warning(
                f"Message dispatch rejected | User: {request.user_id} | code: {outcome.error_code}"
            )
            return MessageResponse(
                success=False,
                message=outcome.error_message or core_i18n.t("chat.dispatch.failed_to_queue", fallback="Failed to queue message"),
                data={
                    "user_id": request.user_id,
                    "session_id": outcome.session_id,
                    "error": outcome.error_message,
                    "error_code": outcome.error_code,
                },
            )

        if outcome.handled_as == "ask_response":
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

        logger.info(
            "Message from %s queued for runtime processing | Queue size: %s",
            request.user_id,
            outcome.queue_size if outcome.queue_size is not None else "unknown",
        )

        agent_logger.info(
            "Message received | User: %s | Content: '%s%s' | Length: %s",
            request.user_id,
            request.message[:50],
            "..." if len(request.message) > 50 else "",
            len(request.message),
        )

        return MessageResponse(
            success=True,
            message=core_i18n.t("chat.dispatch.queued", fallback="Message queued for processing"),
            data={
                "user_id": request.user_id,
                "session_id": outcome.session_id,
                "turn_id": outcome.turn_id,
                "message_length": len(request.message),
                "attachment_count": len(request.attachments or []),
                "timestamp": time.time(),
            }
        )
    except Exception as e:
        logger.error(f"Failed to queue message: {e}")
        agent_logger.error(f"Queue failed | User: {request.user_id} | error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["RUNTIME_NOT_READY", "message_dispatch_router", "send_user_message", "_ensure_runtime_ready_for_user_message"]