"""Chat-owned user-message ingress service."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..core.logger import get_logger
from ..core.runtime_bindings import get_chat_message_notifier, require_runtime_command_queue
from ..events.contracts import UserMessageCommand
from ..events.recall_feedback import (
    RECALL_FEEDBACK_INTERACTION_KIND,
    RecallFeedbackRequest,
)
from ..events.user_message_dispatch import (
    ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED,
    ASK_RESPONSE_RESOLVE_FAILED,
    CHAT_STORE_NOT_INITIALIZED,
    CHAT_STORE_PERSIST_FAILED,
    EMPTY_TURN,
    MALFORMED_ATTACHMENTS,
    RECALL_FEEDBACK_PENDING_ASK,
    MessageDispatchOutcome,
    RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
    RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED,
    SESSION_ID_REQUIRED,
)
from ..i18n import t
from ..core.runtime_namespace import DEFAULT_RUNTIME_NAMESPACE
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


@dataclass(slots=True)
class _IngressDependencies:
    runtime_command_queue: Any
    chat_store: Any


@dataclass(slots=True)
class _ValidatedUserMessage:
    session_id: str
    message: str
    attachments: list[dict[str, Any]]


@dataclass(slots=True)
class _UserMessageSubmission:
    source: str
    user_id: str
    session_id: str
    turn_id: str
    message: str
    attachments: list[dict[str, Any]]
    reply_to_message_id: str | None
    workspace_path: str | None
    metadata: dict[str, Any]
    runtime_namespace: str


@dataclass(slots=True)
class _PersistedUserTurn:
    created_turn: Any
    created_at: float
    created_at_ms: int


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

    from ..control.provider import (
        resolve_control_interaction_broker as _resolve_control_interaction_broker,
    )

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

    recall_feedback = RecallFeedbackRequest.from_value((metadata or {}).get("recall_feedback"))
    user_id, dependencies, validated, early_outcome = await _prepare_ingress_start(
        user_id=user_id,
        session_id=session_id,
        message=message,
        attachments=attachments,
        is_recall_feedback=recall_feedback is not None,
    )
    if early_outcome is not None:
        return early_outcome
    assert dependencies is not None and validated is not None

    # This shared boundary makes attachment preparation, chat persistence, L1
    # projection, and runtime enqueue one indivisible operation relative to a
    # destructive memory clear. The clear path acquires the matching exclusive
    # boundary before it enters the memory barrier, preserving lock order.
    async with dependencies.runtime_command_queue.user_message_operation():
        submission = await _prepare_user_message_submission(
            source=source,
            user_id=user_id,
            validated=validated,
            reply_to_message_id=reply_to_message_id,
            workspace_path=workspace_path,
            client_turn_id=client_turn_id,
            metadata=metadata,
            runtime_namespace=runtime_namespace,
        )
        hook_error = await _apply_user_prompt_submit_hook(submission)
        if hook_error is not None:
            return hook_error

        persisted, persist_error = await _persist_user_message_turn(
            dependencies.chat_store,
            submission,
        )
        if persist_error is not None:
            return persist_error
        assert persisted is not None

        await _project_user_message(submission, persisted)
        enqueue_error = await _enqueue_runtime_user_message(
            dependencies.runtime_command_queue,
            submission,
            persisted,
        )
        if enqueue_error is not None:
            return enqueue_error

        return await _build_successful_dispatch_outcome(
            dependencies.runtime_command_queue,
            submission,
            persisted,
        )


async def _prepare_ingress_start(
    *,
    user_id: str,
    session_id: str | None,
    message: str,
    attachments: list[dict[str, Any]] | None,
    is_recall_feedback: bool,
) -> tuple[
    str,
    _IngressDependencies | None,
    _ValidatedUserMessage | None,
    MessageDispatchOutcome | None,
]:
    from ..identity import canonicalize_user_id

    user_id = str(canonicalize_user_id(user_id))
    dependencies, dependency_error = _resolve_ingress_dependencies(user_id)
    if dependency_error is not None:
        return user_id, None, None, dependency_error
    validated, validation_error = _validate_user_message_input(
        user_id=user_id,
        session_id=session_id,
        message=message,
        attachments=attachments,
    )
    if validation_error is not None:
        return user_id, dependencies, None, validation_error
    assert validated is not None
    if is_recall_feedback:
        ask_state = _active_pending_ask_state(validated.session_id)
        if ask_state is not None:
            return (
                user_id,
                dependencies,
                validated,
                MessageDispatchOutcome(
                    success=False,
                    user_id=user_id,
                    session_id=validated.session_id,
                    handled_as="recall_feedback",
                    ask_request_id=ask_state.request_id,
                    error_code=RECALL_FEEDBACK_PENDING_ASK,
                    error_message=t(
                        "chat.dispatch.errors.recall_feedback_pending_ask",
                        fallback="Answer the current question before rechecking an earlier reply.",
                    ),
                ),
            )
    ask_outcome = await _resolve_pending_ask_response(
        user_id=user_id,
        session_id=validated.session_id,
        answer=validated.message.strip(),
        has_attachments=bool(validated.attachments),
    )
    return user_id, dependencies, validated, ask_outcome


def _resolve_ingress_dependencies(
    user_id: str,
) -> tuple[_IngressDependencies | None, MessageDispatchOutcome | None]:
    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError:
        return None, MessageDispatchOutcome(
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
        return None, MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=CHAT_STORE_NOT_INITIALIZED,
            error_message=t(
                "chat.dispatch.errors.chat_store_not_initialized",
                fallback="Chat store is not initialized.",
            ),
        )
    return _IngressDependencies(runtime_command_queue, chat_store), None


def _validate_user_message_input(
    *,
    user_id: str,
    session_id: str | None,
    message: str,
    attachments: list[dict[str, Any]] | None,
) -> tuple[_ValidatedUserMessage | None, MessageDispatchOutcome | None]:
    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=SESSION_ID_REQUIRED,
            error_message=t(
                "chat.dispatch.errors.session_id_required",
                fallback="Session ID is required.",
            ),
        )
    try:
        normalized_attachments = _normalize_attachments(attachments)
    except ValueError as exc:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            error_code=MALFORMED_ATTACHMENTS,
            error_message=str(exc),
        )
    normalized_message = str(message or "")
    if not normalized_message.strip() and not normalized_attachments:
        return None, _empty_turn_outcome(user_id, resolved_session_id)
    return (
        _ValidatedUserMessage(
            session_id=resolved_session_id,
            message=normalized_message,
            attachments=normalized_attachments,
        ),
        None,
    )


async def _prepare_user_message_submission(
    *,
    source: str,
    user_id: str,
    validated: _ValidatedUserMessage,
    reply_to_message_id: str | None,
    workspace_path: str | None,
    client_turn_id: str | None,
    metadata: dict[str, Any] | None,
    runtime_namespace: str | None,
) -> _UserMessageSubmission:
    turn_id = str(client_turn_id or "").strip() or f"turn_{uuid.uuid4().hex[:12]}"
    prepared_attachments = await _prepare_runtime_attachments(
        session_id=validated.session_id,
        turn_id=turn_id,
        attachments=validated.attachments,
    )
    normalized_workspace_path = await _resolve_workspace_path(
        user_id=user_id,
        session_id=validated.session_id,
        workspace_path=workspace_path,
    )
    normalized_reply_to_message_id = str(reply_to_message_id or "").strip() or None
    normalized_metadata = dict(metadata or {})
    if normalized_reply_to_message_id is not None:
        normalized_metadata["reply_to_message_id"] = normalized_reply_to_message_id
    return _UserMessageSubmission(
        source=source,
        user_id=user_id,
        session_id=validated.session_id,
        turn_id=turn_id,
        message=validated.message,
        attachments=prepared_attachments,
        reply_to_message_id=normalized_reply_to_message_id,
        workspace_path=normalized_workspace_path,
        metadata=normalized_metadata,
        runtime_namespace=str(runtime_namespace or "").strip() or DEFAULT_RUNTIME_NAMESPACE,
    )


async def _resolve_workspace_path(
    *,
    user_id: str,
    session_id: str,
    workspace_path: str | None,
) -> str | None:
    normalized_workspace_path = str(workspace_path or "").strip() or None
    if normalized_workspace_path is not None:
        return normalized_workspace_path
    try:
        read_service = get_chat_read_service()
        session_summary = await read_service.aget_session_summary(user_id, session_id)
    except Exception:
        return None
    if session_summary is None:
        return None
    return str(session_summary.workspace_path or "").strip() or None


def _empty_turn_outcome(
    user_id: str, session_id: str, turn_id: str | None = None
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        error_code=EMPTY_TURN,
        error_message=t(
            "chat.dispatch.errors.empty_turn",
            fallback="Message text or attachments are required.",
        ),
    )


async def _apply_user_prompt_submit_hook(
    submission: _UserMessageSubmission,
) -> MessageDispatchOutcome | None:
    from ..hooks.contracts import HookEventType, HookOutcome
    from ..hooks.dispatch import dispatch_hook

    submit_decision = await dispatch_hook(
        HookEventType.USER_PROMPT_SUBMIT,
        session_id=submission.session_id,
        turn_id=submission.turn_id,
        user_id=submission.user_id,
        workspace=submission.workspace_path,
        user_message=submission.message,
        extra={
            "source": submission.source,
            "has_attachments": bool(submission.attachments),
            "reply_to_message_id": submission.reply_to_message_id,
        },
    )
    if submit_decision.outcome == HookOutcome.DENY:
        return MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            error_code="HOOK_DENIED",
            error_message=submit_decision.reason or "User prompt rejected by hook",
        )
    if submit_decision.outcome == HookOutcome.MODIFY:
        return _apply_modified_user_message(submission, submit_decision.modified_user_message)
    if submit_decision.outcome == HookOutcome.INJECT_CONTEXT and submit_decision.additional_context:
        submission.metadata.setdefault("hook_injected_context", submit_decision.additional_context)
    return None


def _apply_modified_user_message(
    submission: _UserMessageSubmission,
    modified_message: str | None,
) -> MessageDispatchOutcome | None:
    if modified_message is None:
        return None
    submission.message = modified_message
    if not submission.message.strip() and not submission.attachments:
        return _empty_turn_outcome(
            submission.user_id,
            submission.session_id,
            submission.turn_id,
        )
    return None


async def _persist_user_message_turn(
    chat_store: Any,
    submission: _UserMessageSubmission,
) -> tuple[_PersistedUserTurn | None, MessageDispatchOutcome | None]:
    created_at = time.time()
    created_at_ms = int(created_at * 1000)
    active_persona_id = await _resolve_active_persona_id()
    recall_feedback = RecallFeedbackRequest.from_value(submission.metadata.get("recall_feedback"))
    try:
        created_turn = await chat_store.create_user_turn(
            session_id=submission.session_id,
            user_id=submission.user_id,
            turn_id=submission.turn_id,
            message_text=submission.message,
            attachment_payloads=submission.attachments,
            message_payload=(
                {"recall_feedback": recall_feedback.to_dict()}
                if recall_feedback is not None
                else None
            ),
            created_at_ms=created_at_ms,
            reply_to_message_id=submission.reply_to_message_id,
            persona_id=active_persona_id,
        )
    except Exception:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            error_code=CHAT_STORE_PERSIST_FAILED,
            error_message=t(
                "chat.dispatch.errors.persist_failed",
                fallback="Chat turn persistence failed",
            ),
        )
    return _PersistedUserTurn(created_turn, created_at, created_at_ms), None


async def _project_user_message(
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> None:
    recall_feedback = RecallFeedbackRequest.from_value(submission.metadata.get("recall_feedback"))
    try:
        chat_projector = get_chat_projector()
    except RuntimeError:
        chat_projector = None
    if chat_projector is None:
        return
    try:
        await chat_projector.project_user_message(
            message_id=persisted.created_turn.message_id,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            content=submission.message,
            created_at_ms=persisted.created_at_ms,
            interaction_kind=(
                RECALL_FEEDBACK_INTERACTION_KIND if recall_feedback is not None else None
            ),
            metadata=_extract_chat_projection_metadata(submission.metadata),
        )
    except Exception as exc:
        logger.warning("Failed to project chat user message into L1: %s", exc)


async def _enqueue_runtime_user_message(
    runtime_command_queue: Any,
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> MessageDispatchOutcome | None:
    try:
        await runtime_command_queue.enqueue_user_message(
            UserMessageCommand(
                source=submission.source,
                user_id=submission.user_id,
                session_id=submission.session_id,
                turn_id=submission.turn_id,
                message=submission.message,
                attachments=submission.attachments,
                workspace_path=submission.workspace_path,
                runtime_namespace=submission.runtime_namespace,
                metadata=submission.metadata,
                created_at=persisted.created_at,
            )
        )
    except Exception:
        return MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            error_code=RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
            error_message=t(
                "chat.dispatch.errors.enqueue_failed",
                fallback="Runtime command enqueue failed",
            ),
        )
    return None


async def _build_successful_dispatch_outcome(
    runtime_command_queue: Any,
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> MessageDispatchOutcome:
    stats = await runtime_command_queue.get_stats()
    queue_size = stats.get("pending_count") if isinstance(stats, dict) else None
    await get_chat_message_notifier().broadcast_chat_message_upsert(
        user_id=submission.user_id,
        session_id=submission.session_id,
        message_id=persisted.created_turn.message_id,
    )
    return MessageDispatchOutcome(
        success=True,
        user_id=submission.user_id,
        session_id=submission.session_id,
        turn_id=submission.turn_id,
        message_id=persisted.created_turn.message_id,
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
    ask_state = _active_pending_ask_state(session_id)
    if ask_state is None:
        return None

    if has_attachments:
        return _ask_response_attachments_unsupported(user_id, session_id, ask_state.request_id)

    try:
        broker = resolve_control_interaction_broker()
    except RuntimeError:
        return _ask_response_resolve_failed(user_id, session_id, ask_state.request_id)

    resolved = await broker.resolve(
        interaction_id=ask_state.request_id,
        kind="ask",
        response=answer,
    )
    if not resolved:
        return _ask_response_resolve_failed(user_id, session_id, ask_state.request_id)

    return _ask_response_success(user_id, session_id, ask_state.request_id)


def _lookup_pending_ask_state(session_id: str) -> Any | None:
    try:
        store = resolve_control_session_store()
        return store.ask_state(session_id)
    except RuntimeError:
        return None
    except Exception:
        logger.debug(
            "message_dispatch.ask_state_lookup_failed", session_id=session_id, exc_info=True
        )
        return None


def _active_pending_ask_state(session_id: str) -> Any | None:
    ask_state = _lookup_pending_ask_state(session_id)
    if ask_state is None or ask_state.status != "pending":
        return None
    if ask_state.expires_at is not None and ask_state.expires_at <= time.time():
        return None
    return ask_state


def _ask_response_attachments_unsupported(
    user_id: str,
    session_id: str,
    ask_request_id: str,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=user_id,
        session_id=session_id,
        handled_as="ask_response",
        ask_request_id=ask_request_id,
        error_code=ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED,
        error_message=t(
            "chat.dispatch.errors.ask_response_attachments_unsupported",
            fallback="Attachments cannot be used as an answer to this question. Please send a text answer only.",
        ),
    )


def _ask_response_resolve_failed(
    user_id: str,
    session_id: str,
    ask_request_id: str,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=user_id,
        session_id=session_id,
        handled_as="ask_response",
        ask_request_id=ask_request_id,
        error_code=ASK_RESPONSE_RESOLVE_FAILED,
        error_message=t(
            "chat.dispatch.errors.ask_response_resolve_failed",
            fallback="The question is no longer waiting for an answer.",
        ),
    )


def _ask_response_success(
    user_id: str,
    session_id: str,
    ask_request_id: str,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=session_id,
        handled_as="ask_response",
        ask_request_id=ask_request_id,
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
        raise ValueError(
            t(
                "chat.dispatch.errors.attachments_must_be_list",
                fallback="Attachments must be a list.",
            )
        )
    normalized: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError(
                t(
                    "chat.dispatch.errors.attachment_must_be_object",
                    fallback="Each attachment must be an object.",
                )
            )
        normalized_item = dict(item)
        attachment_kind = str(normalized_item.get("kind") or "").strip()
        if not attachment_kind:
            raise ValueError(
                t(
                    "chat.dispatch.errors.attachment_kind_required",
                    fallback="Each attachment must include a kind.",
                )
            )
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
    "RECALL_FEEDBACK_PENDING_ASK",
    "SESSION_ID_REQUIRED",
    "dispatch_user_message",
    "get_chat_read_service",
    "get_chat_projector",
    "get_chat_store",
    "require_runtime_command_queue",
    "resolve_control_interaction_broker",
    "resolve_control_session_store",
]
