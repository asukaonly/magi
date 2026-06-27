"""Chat-owned user-message ingress service."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from ..core.logger import get_logger
from ..core.runtime_bindings import get_chat_message_notifier, require_runtime_command_queue
from ..events.contracts import UserMessageCommand
from ..events.user_message_dispatch import (
    ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED,
    ASK_RESPONSE_RESOLVE_FAILED,
    CHAT_STORE_NOT_INITIALIZED,
    CHAT_STORE_PERSIST_FAILED,
    EMPTY_TURN,
    MALFORMED_ATTACHMENTS,
    MessageDispatchOutcome,
    RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
    RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED,
    SESSION_ID_REQUIRED,
)
from ..i18n import t
from ..runtime_defaults import DEFAULT_RUNTIME_NAMESPACE
from .attachment_ingestion import LocalChatAttachmentIngestionService
from .provider import get_chat_projector, get_chat_store

logger = get_logger(__name__)

_CHAT_PROJECTION_METADATA_KEYS = {
    "l2_batch_owner",
    "l2_batch_catch_up_owner",
    "l2_batch_max_events",
    "l2_batch_min_ready_events",
    "l2_batch_max_wait_seconds",
}


def get_chat_read_service():
    """Resolve the chat read service lazily to avoid startup cycles."""

    from .read_service import get_chat_read_service as _get_chat_read_service

    return _get_chat_read_service()


def resolve_control_session_store():
    """Resolve the control session store lazily to avoid startup cycles."""

    from ..control.provider import resolve_control_session_store as _resolve_control_session_store

    return _resolve_control_session_store()


def resolve_control_interaction_broker():
    """Resolve the control interaction broker lazily to avoid startup cycles."""

    from ..control.provider import resolve_control_interaction_broker as _resolve_control_interaction_broker

    return _resolve_control_interaction_broker()


def _extract_chat_projection_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in _CHAT_PROJECTION_METADATA_KEYS and value is not None
    }


async def dispatch_user_message(
    *,
    source: str,
    user_id: str,
    message: str,
    session_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    reply_to_message_id: str | None = None,
    workspace_path: str | None = None,
    client_turn_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    runtime_namespace: str | None = None,
) -> MessageDispatchOutcome:
    """Resolve chat-owned metadata and enqueue a user-message runtime command."""

    from ..identity import canonicalize_user_id

    user_id = str(canonicalize_user_id(user_id))

    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED,
            error_message=t(
                "chat.dispatch.errors.runtime_command_queue_not_initialized",
                fallback="Runtime command queue is not initialized. Please complete onboarding or check the saved configuration.",
            ),
        )
    try:
        chat_store = get_chat_store()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=CHAT_STORE_NOT_INITIALIZED,
            error_message=t("chat.dispatch.errors.chat_store_not_initialized", fallback="Chat store is not initialized."),
        )

    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=SESSION_ID_REQUIRED,
            error_message=t("chat.dispatch.errors.session_id_required", fallback="Session ID is required."),
        )
    try:
        normalized_attachments = _normalize_attachments(attachments)
    except ValueError as exc:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            error_code=MALFORMED_ATTACHMENTS,
            error_message=str(exc),
        )
    normalized_message = str(message or "")
    if not normalized_message.strip() and not normalized_attachments:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            error_code=EMPTY_TURN,
            error_message=t("chat.dispatch.errors.empty_turn", fallback="Message text or attachments are required."),
        )
    ask_outcome = await _resolve_pending_ask_response(
        user_id=user_id,
        session_id=resolved_session_id,
        answer=normalized_message.strip(),
        has_attachments=bool(normalized_attachments),
    )
    if ask_outcome is not None:
        return ask_outcome
    turn_id = str(client_turn_id or "").strip() or f"turn_{uuid.uuid4().hex[:12]}"
    normalized_attachments = await _prepare_runtime_attachments(
        session_id=resolved_session_id,
        turn_id=turn_id,
        attachments=normalized_attachments,
    )
    normalized_workspace_path = str(workspace_path or "").strip() or None
    if normalized_workspace_path is None:
        try:
            read_service = get_chat_read_service()
            session_summary = await read_service.aget_session_summary(user_id, resolved_session_id)
        except Exception:
            session_summary = None
        if session_summary is not None:
            normalized_workspace_path = str(session_summary.workspace_path or "").strip() or None
    normalized_reply_to_message_id = str(reply_to_message_id or "").strip() or None
    normalized_metadata = dict(metadata or {})
    if normalized_reply_to_message_id is not None:
        normalized_metadata["reply_to_message_id"] = normalized_reply_to_message_id

    from ..hooks.contracts import HookEventType, HookOutcome
    from ..hooks.dispatch import dispatch_hook

    submit_decision = await dispatch_hook(
        HookEventType.USER_PROMPT_SUBMIT,
        session_id=resolved_session_id,
        turn_id=turn_id,
        user_id=user_id,
        workspace=normalized_workspace_path,
        user_message=normalized_message,
        extra={
            "source": source,
            "has_attachments": bool(normalized_attachments),
            "reply_to_message_id": normalized_reply_to_message_id,
        },
    )
    if submit_decision.outcome == HookOutcome.DENY:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            turn_id=turn_id,
            error_code="HOOK_DENIED",
            error_message=submit_decision.reason or "User prompt rejected by hook",
        )
    if submit_decision.outcome == HookOutcome.MODIFY and submit_decision.modified_user_message is not None:
        normalized_message = submit_decision.modified_user_message
        if not normalized_message.strip() and not normalized_attachments:
            return MessageDispatchOutcome(
                success=False,
                user_id=user_id,
                session_id=resolved_session_id,
                turn_id=turn_id,
                error_code=EMPTY_TURN,
                error_message=t(
                    "chat.dispatch.errors.empty_turn",
                    fallback="Message text or attachments are required.",
                ),
            )
    elif submit_decision.outcome == HookOutcome.INJECT_CONTEXT and submit_decision.additional_context:
        normalized_metadata.setdefault("hook_injected_context", submit_decision.additional_context)

    created_at = time.time()
    created_at_ms = int(created_at * 1000)
    active_persona_id = await _resolve_active_persona_id()
    try:
        created_turn = await chat_store.create_user_turn(
            session_id=resolved_session_id,
            user_id=user_id,
            turn_id=turn_id,
            message_text=normalized_message,
            attachment_payloads=normalized_attachments,
            created_at_ms=created_at_ms,
            reply_to_message_id=normalized_reply_to_message_id,
            persona_id=active_persona_id,
        )
    except Exception:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            turn_id=turn_id,
            error_code=CHAT_STORE_PERSIST_FAILED,
            error_message=t("chat.dispatch.errors.persist_failed", fallback="Chat turn persistence failed"),
        )
    try:
        chat_projector = get_chat_projector()
    except RuntimeError:
        chat_projector = None
    if chat_projector is not None:
        try:
            await chat_projector.project_user_message(
                message_id=created_turn.message_id,
                user_id=user_id,
                session_id=resolved_session_id,
                turn_id=turn_id,
                content=normalized_message,
                created_at_ms=created_at_ms,
                metadata=_extract_chat_projection_metadata(normalized_metadata),
            )
        except Exception as exc:
            logger.warning("Failed to project chat user message into L1: %s", exc)
    try:
        await runtime_command_queue.enqueue_user_message(
            UserMessageCommand(
                source=source,
                user_id=user_id,
                session_id=resolved_session_id,
                turn_id=turn_id,
                message=normalized_message,
                attachments=normalized_attachments,
                workspace_path=normalized_workspace_path,
                runtime_namespace=str(runtime_namespace or "").strip() or DEFAULT_RUNTIME_NAMESPACE,
                metadata=normalized_metadata,
                created_at=created_at,
            )
        )
    except Exception:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            turn_id=turn_id,
            error_code=RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
            error_message=t("chat.dispatch.errors.enqueue_failed", fallback="Runtime command enqueue failed"),
        )

    stats = await runtime_command_queue.get_stats()
    queue_size = stats.get("pending_count") if isinstance(stats, dict) else None
    await get_chat_message_notifier().broadcast_chat_message_upsert(
        user_id=user_id,
        session_id=resolved_session_id,
        message_id=created_turn.message_id,
    )
    return MessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=resolved_session_id,
        turn_id=turn_id,
        message_id=created_turn.message_id,
        queue_size=int(queue_size) if isinstance(queue_size, int) else None,
    )


async def _resolve_pending_ask_response(
    *,
    user_id: str,
    session_id: str,
    answer: str,
    has_attachments: bool = False,
) -> MessageDispatchOutcome | None:
    if not answer:
        return None
    try:
        store = resolve_control_session_store()
        ask_state = store.ask_state(session_id)
    except RuntimeError:
        return None
    except Exception:
        logger.debug("message_dispatch.ask_state_lookup_failed", session_id=session_id, exc_info=True)
        return None

    if ask_state is None or ask_state.status != "pending":
        return None
    if ask_state.expires_at is not None and ask_state.expires_at <= time.time():
        return None

    if has_attachments:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=session_id,
            handled_as="ask_response",
            ask_request_id=ask_state.request_id,
            error_code=ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED,
            error_message=t(
                "chat.dispatch.errors.ask_response_attachments_unsupported",
                fallback="Attachments cannot be used as an answer to this question. Please send a text answer only.",
            ),
        )

    try:
        broker = resolve_control_interaction_broker()
    except RuntimeError:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=session_id,
            handled_as="ask_response",
            ask_request_id=ask_state.request_id,
            error_code=ASK_RESPONSE_RESOLVE_FAILED,
            error_message=t(
                "chat.dispatch.errors.ask_response_resolve_failed",
                fallback="The question is no longer waiting for an answer.",
            ),
        )

    resolved = await broker.resolve(
        interaction_id=ask_state.request_id,
        kind="ask",
        response=answer,
    )
    if not resolved:
        return MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=session_id,
            handled_as="ask_response",
            ask_request_id=ask_state.request_id,
            error_code=ASK_RESPONSE_RESOLVE_FAILED,
            error_message=t(
                "chat.dispatch.errors.ask_response_resolve_failed",
                fallback="The question is no longer waiting for an answer.",
            ),
        )

    return MessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=session_id,
        handled_as="ask_response",
        ask_request_id=ask_state.request_id,
    )


async def _resolve_active_persona_id() -> str | None:
    try:
        from ..personality.persona_repository import PersonaRepository
        from ..utils.runtime import get_runtime_paths

        repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
        await repo.init()
        active_id = await repo.get_active_id()
    except Exception:
        return None
    return str(active_id or "").strip() or None


def _normalize_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise ValueError(t("chat.dispatch.errors.attachments_must_be_list", fallback="Attachments must be a list."))
    normalized: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError(t("chat.dispatch.errors.attachment_must_be_object", fallback="Each attachment must be an object."))
        normalized_item = dict(item)
        attachment_kind = str(normalized_item.get("kind") or "").strip()
        if not attachment_kind:
            raise ValueError(t("chat.dispatch.errors.attachment_kind_required", fallback="Each attachment must include a kind."))
        normalized_item["kind"] = attachment_kind
        normalized.append(normalized_item)
    return normalized


async def _prepare_runtime_attachments(
    *,
    session_id: str,
    turn_id: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not attachments:
        return []
    ingestion_service = LocalChatAttachmentIngestionService()
    return await asyncio.to_thread(
        _prepare_runtime_attachments_sync,
        ingestion_service,
        session_id,
        turn_id,
        attachments,
    )


def _prepare_runtime_attachments_sync(
    ingestion_service: LocalChatAttachmentIngestionService,
    session_id: str,
    turn_id: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for attachment in attachments:
        prepared.append(
            ingestion_service.prepare_runtime_attachment(
                session_id=session_id,
                turn_id=turn_id,
                attachment=attachment,
            )
        )
    return prepared


__all__ = [
    "ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED",
    "ASK_RESPONSE_RESOLVE_FAILED",
    "CHAT_STORE_NOT_INITIALIZED",
    "CHAT_STORE_PERSIST_FAILED",
    "EMPTY_TURN",
    "MALFORMED_ATTACHMENTS",
    "MessageDispatchOutcome",
    "RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED",
    "RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED",
    "SESSION_ID_REQUIRED",
    "dispatch_user_message",
    "get_chat_read_service",
    "get_chat_projector",
    "get_chat_store",
    "require_runtime_command_queue",
    "resolve_control_interaction_broker",
    "resolve_control_session_store",
]
